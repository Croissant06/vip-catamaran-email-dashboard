from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from dateutil import parser as date_parser
import logging
import re
import unicodedata

from bs4 import BeautifulSoup
from langdetect import LangDetectException, detect
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.models import City, Hotel

logger = logging.getLogger(__name__)

BOOKING_TRIGGER = "you have just received a new booking!"
BOOKEO_TRIGGER = "powered by bookeo"
BUS_KEYWORDS = {
    "bus",
    "pickup",
    "pick up",
    "stop",
    "hotel",
    "cruise",
    "transfer",
    "coach",
    "port",
}
SUPPORTED_LANGUAGE_MAP = {
    "english": "en",
    "en": "en",
    "spanish": "es",
    "es": "es",
    "espanol": "es",
    "french": "fr",
    "fr": "fr",
    "francais": "fr",
    "german": "de",
    "de": "de",
    "deutsch": "de",
    "italian": "it",
    "it": "it",
    "italiano": "it",
    "greek": "el",
    "el": "el",
    "ellinika": "el",
    "ellhnika": "el",
    "ελληνικα": "el",
    "ελληνικά": "el",
    "russian": "ru",
    "ru": "ru",
    "russkiy": "ru",
    "русский": "ru",
    "polish": "pl",
    "pl": "pl",
    "polski": "pl",
}
CITY_HINTS = {
    "sunny beach": "Sunny Beach",
    "slanchev bryag": "Sunny Beach",
    "slunchev bryag": "Sunny Beach",
    "obzor": "Obzor",
    "pomorie": "Pomorie",
    "pomori": "Pomorie",
}
COMMERCIAL_VENUE_FLAGS = {
    "spiders pub": "Booking references Spiders Pub which is not a hotel. Customer may have entered wrong hotel name. Manual assignment required."
}
INVALID_HOTEL_FIELD_VALUES = {
    "",
    "(empty)",
    "empty",
    "invalid selection",
    "n/a",
    "na",
    "none",
    "unknown",
    "not sure",
    "i do not know",
    "i don't know",
    "to be confirmed",
}
BOOKING_TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ANASTASIA", ("anastasia", "st anastasia", "saint anastasia")),
    ("OBZOR", ("obzor and old nessebar", "obzor old nessebar", "obzor")),
    ("POMORIE", ("pomorie vip catamaran", "pomorie")),
    ("SUNSET", ("sunset cruise vip catamaran", "sunset vip catamaran", "sunset cruise", "sunset")),
    ("AFTERNOON", ("afternoon vip catamaran", "afternoon catamaran", "afternoon")),
    ("MORNING", ("morning vip catamaran", "morning catamaran", "morning")),
)
HOTEL_HINT_TOKENS = (
    "hotel",
    "resort",
    "apart",
    "complex",
    "suites",
    "spa",
    "villas",
    "palace",
    "park",
    "club",
    "plaza",
    "beach",
    "bay",
    "house",
    "marina",
    "wave",
)


@dataclass
class BookingParseResult:
    cruise_date: date | None = None
    cruise_time: time | None = None
    excursion: str = ""
    booking_type: str = ""
    num_adults: int | None = None
    num_children: int | None = None
    booking_number: str = ""
    total_price: str = ""
    customer_name: str = ""
    customer_email: str = ""
    customer_phone: str = ""
    preferred_language: str = ""
    template_language: str = "en"
    notes_block: str = ""
    hotel_name_field: str = ""
    bus_stop_field: str = ""
    raw_customer_name_extraction: str = ""
    raw_hotel_extraction: str = ""
    extraction_source: str = "failed"
    city_name: str = ""
    gyg_ref: str = ""
    warning_note: str = ""


@dataclass
class ClassificationResult:
    language: str
    matched_hotel: Hotel | None
    score: float
    is_bus_request: bool
    is_booking_email: bool
    booking_type: str
    cruise_date: date | None
    cruise_time: time | None
    num_adults: int | None
    num_children: int | None
    booking_number: str
    total_price: str
    customer_name: str
    customer_email: str
    customer_phone: str
    raw_customer_name_extraction: str
    raw_hotel_extraction: str
    extraction_source: str
    city: City | None
    gyg_ref: str
    warning_note: str


def detect_language(text: str) -> str:
    sample = (text or "").strip()
    if not sample:
        return "en"
    try:
        return detect(sample)
    except LangDetectException:
        return "en"


def is_booking_email(subject: str, body: str) -> bool:
    haystack = f"{subject}\n{body}".lower()
    return BOOKING_TRIGGER in haystack or BOOKEO_TRIGGER in haystack


def is_bus_stop_email(subject: str, body: str) -> bool:
    if is_booking_email(subject, body):
        return True
    haystack = f"{subject} {body}".lower()
    return any(keyword in haystack for keyword in BUS_KEYWORDS)


def _hotel_candidates(hotel: Hotel) -> list[str]:
    aliases = [part.strip() for part in hotel.aliases.split(",") if part.strip()]
    return [hotel.name, *aliases]


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.replace("&", " and ")
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_text.lower())
    return _normalize_spaces(ascii_text)


def _store_lookup(lookup: dict[str, str], key: str, value: str) -> None:
    normalized_key = _normalize_token(key).rstrip(":")
    normalized_value = _normalize_spaces(value)
    if normalized_key and normalized_value and normalized_key not in lookup:
        lookup[normalized_key] = normalized_value


def _build_label_map(html_body: str, text_body: str) -> dict[str, str]:
    """Parse Bookeo's layout into a case-insensitive label/value lookup."""

    lookup: dict[str, str] = {}
    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            for index in range(0, len(cells) - 1, 2):
                _store_lookup(lookup, cells[index], cells[index + 1])

        for term in soup.find_all("dt"):
            description = term.find_next_sibling("dd")
            if description:
                _store_lookup(lookup, term.get_text(" ", strip=True), description.get_text(" ", strip=True))

        for element in soup.find_all(["p", "li", "div"]):
            line = _normalize_spaces(element.get_text(" ", strip=True))
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if len(key.split()) <= 6:
                _store_lookup(lookup, key, value)

    if text_body:
        for line in text_body.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            _store_lookup(lookup, key, value)
    return lookup


def _lookup_value(label_map: dict[str, str], *labels: str) -> str:
    for label in labels:
        value = label_map.get(_normalize_token(label))
        if value:
            return value
    return ""


def _looks_like_customer_name(value: str) -> bool:
    candidate = _normalize_spaces(str(value or "").strip(" '\""))
    if not candidate or "@" in candidate or ":" in candidate:
        return False
    if not any(char.isalpha() for char in candidate):
        return False
    disallowed = {"email", "customer", "phone", "preferred language"}
    return candidate.lower() not in disallowed


def _parse_date(value: str) -> date | None:
    cleaned = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", value.strip(), flags=re.IGNORECASE)
    cleaned = cleaned.replace(" ,", ",")
    if not cleaned:
        return None
    try:
        return date_parser.parse(cleaned, dayfirst=True, fuzzy=True).date()
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_time(value: str) -> time | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%H:%M", "%H.%M", "%I:%M %p", "%I:%M%p", "%I %p"):
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    return None


def _parse_num_adults(value: str) -> int | None:
    lowered = value.lower()
    for pattern in (
        r"(\d+)\s*x?\s*adult(?:s)?\b",
        r"adult(?:s)?\s*[:\-]?\s*(\d+)\b",
        r"(\d+)\s*passenger(?:s)?\b",
    ):
        match = re.search(pattern, lowered)
        if match:
            return int(match.group(1))
    fallback = re.search(r"\b(\d+)\b", value)
    return int(fallback.group(1)) if fallback else None


def _parse_num_children(value: str) -> int | None:
    lowered = value.lower()
    for pattern in (
        r"(\d+)\s*x?\s*child(?:ren)?\b",
        r"child(?:ren)?\s*[:\-]?\s*(\d+)\b",
    ):
        match = re.search(pattern, lowered)
        if match:
            return int(match.group(1))
    return None


def _fallback_name_from_email(customer_email: str) -> str:
    local_part = (customer_email or "").split("@", 1)[0]
    if local_part.lower().startswith("customer-"):
        candidate = local_part.split("-", 1)[1].strip()
        if re.fullmatch(r"[a-z0-9]{8,}", candidate, flags=re.IGNORECASE):
            return "Valued Guest"
        candidate = re.sub(r"[._-]+", " ", candidate).strip()
        if _looks_like_customer_name(candidate):
            return candidate.title()
        return "Valued Guest"
    cleaned = re.sub(r"[._-]+", " ", local_part).strip()
    return cleaned.title() if _looks_like_customer_name(cleaned) else "Valued Guest"


def _extract_customer_name(html_body: str, label_map: dict[str, str], fallback_name: str, customer_email: str) -> tuple[str, str]:
    raw_name = ""
    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")

        customer_heading = soup.find(string=re.compile(r"\bcustomer\b", re.IGNORECASE))
        if customer_heading:
            heading_parent = customer_heading.parent
            if heading_parent:
                candidate_strong = heading_parent.find_next("strong")
                if candidate_strong:
                    raw_name = _normalize_spaces(candidate_strong.get_text(" ", strip=True))

        if not _looks_like_customer_name(raw_name):
            email_label = soup.find(string=re.compile(r"^\s*Email\s*:?", re.IGNORECASE))
            if email_label and getattr(email_label, "parent", None):
                for element in email_label.parent.previous_elements:
                    if getattr(element, "name", None) == "strong":
                        raw_name = _normalize_spaces(element.get_text(" ", strip=True))
                        break

        if not _looks_like_customer_name(raw_name):
            for strong in soup.find_all("strong"):
                candidate = _normalize_spaces(strong.get_text(" ", strip=True))
                if _looks_like_customer_name(candidate):
                    raw_name = candidate
                    break

    if not _looks_like_customer_name(raw_name):
        raw_name = _lookup_value(label_map, "customer name", "customer", "name") or fallback_name

    if not _looks_like_customer_name(raw_name):
        return _fallback_name_from_email(customer_email), raw_name
    return raw_name, raw_name


def _extract_reply_email(text_body: str, fallback_sender: str) -> str:
    relay_match = re.search(r"customer-[\w-]+@reply\.getyourguide\.com", text_body, flags=re.IGNORECASE)
    if relay_match:
        return relay_match.group(0)
    return fallback_sender


def _extract_notes_freeform_hotel(notes_block: str) -> str:
    for raw_line in notes_block.splitlines():
        line = _normalize_spaces(raw_line)
        if not line:
            continue
        lowered = line.lower()
        if ":" in line and len(line.split(":", 1)[0].split()) <= 4:
            continue
        if len(line) > 90:
            continue
        if any(token in lowered for token in HOTEL_HINT_TOKENS) or detect_city_name(line):
            stripped = re.split(
                r"\s*[,-]\s*(?:sunny beach|slanchev bryag|obzor|pomorie)\b",
                line,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            return stripped or line
    return ""


def _clean_hotel_candidate(raw_value: str) -> str:
    candidate = _normalize_spaces(str(raw_value or "").strip(" '\""))
    if not candidate:
        return ""
    if "," in candidate:
        candidate = candidate.split(",", 1)[0].strip()
    noise_words = {"hotel", "complex", "resort", "apartments"}
    normalized = _normalize_token(candidate)
    if normalized in noise_words:
        return ""
    return candidate


def _extract_notes_hotel(notes_block: str) -> str:
    notes_lines = [line for line in notes_block.splitlines() if _normalize_spaces(line)]
    for original_line in notes_lines:
        normalized_line = _normalize_spaces(original_line)
        if normalized_line.lower().startswith("hotel:") or normalized_line.lower().startswith("hotel :"):
            raw = normalized_line.split(":", 1)[1].strip()
            return _clean_hotel_candidate(raw)

    match = re.search(r"(?i)(?:^|\n)\s*hotel\s*:\s*([^\n\r]+)", notes_block)
    if match:
        return _clean_hotel_candidate(match.group(1))
    return ""


def detect_city_name(*values: str) -> str:
    haystack = _normalize_token(" ".join(value for value in values if value))
    for hint, matched_city in CITY_HINTS.items():
        if _normalize_token(hint) in haystack:
            return matched_city
    return ""


def detect_city_from_text(db: Session, *values: str) -> City | None:
    city_name = detect_city_name(*values)
    if not city_name:
        return None
    return db.query(City).filter(City.name == city_name).first()


def _resolve_template_language(preferred_language: str) -> tuple[str, str]:
    normalized = _normalize_token(preferred_language)
    if not normalized:
        return "en", ""
    if normalized in SUPPORTED_LANGUAGE_MAP:
        code = SUPPORTED_LANGUAGE_MAP[normalized]
        if code in {"ru", "pl"}:
            return "en", f"Unsupported language: {preferred_language} - defaulted to EN"
        return code, ""
    for key, code in SUPPORTED_LANGUAGE_MAP.items():
        normalized_key = _normalize_token(key)
        if normalized_key and (normalized_key in normalized or normalized in normalized_key):
            if code in {"ru", "pl"}:
                return "en", f"Unsupported language: {preferred_language} - defaulted to EN"
            return code, ""
    return "en", f"Unsupported language: {preferred_language} - defaulted to EN"


def _is_invalid_hotel_field(value: str) -> bool:
    normalized_value = _normalize_token(value)
    invalid_values = {_normalize_token(item) for item in INVALID_HOTEL_FIELD_VALUES}
    return normalized_value in invalid_values


def detect_booking_type(
    subject: str,
    excursion: str,
    cruise_date: date | None = None,
    cruise_time: time | None = None,
    *extra_texts: str,
) -> str:
    subject_normalized = _normalize_token(subject)
    if "obzor" in subject_normalized:
        return "OBZOR"
    if "pomorie" in subject_normalized:
        return "POMORIE"
    if "anastasia" in subject_normalized:
        return "ANASTASIA"
    if "sunset" in subject_normalized:
        return "SUNSET"
    if "afternoon" in subject_normalized:
        return "AFTERNOON"
    if "morning" in subject_normalized:
        return "MORNING"
    combined = _normalize_token(" ".join(part for part in (subject, excursion, *extra_texts) if part))
    for booking_type, hints in BOOKING_TYPE_HINTS:
        if any(hint in combined for hint in hints):
            return booking_type
    if cruise_time:
        if cruise_time.hour >= 18:
            return "SUNSET"
        if cruise_time.hour >= 13:
            return "AFTERNOON"
        return "MORNING"
    if cruise_date and cruise_date.month == 9:
        return "MORNING"
    return ""


def parse_booking_email(subject: str, text_body: str, html_body: str, fallback_sender: str, fallback_name: str) -> BookingParseResult:
    """Extract structured Bookeo/GetYourGuide booking fields from the booking email."""

    label_map = _build_label_map(html_body, text_body)
    combined_text = _normalize_spaces(BeautifulSoup(html_body, "html.parser").get_text("\n", strip=True) if html_body else text_body)
    notes_block = _lookup_value(label_map, "notes")
    hotel_name_field = _lookup_value(label_map, "name of your hotel or complex", "hotel or complex", "hotel name")
    bus_stop_field = _lookup_value(label_map, "choose the pickup point", "pickup point", "pickup location")
    preferred_language = _lookup_value(label_map, "preferred language", "language")
    customer_email = _lookup_value(label_map, "email") or _extract_reply_email(combined_text, fallback_sender)
    customer_name, raw_customer_name_extraction = _extract_customer_name(html_body, label_map, fallback_name, customer_email)
    customer_phone = _lookup_value(label_map, "phone", "mobile", "phone mobile", "phone (mobile)")
    booking_number = _lookup_value(label_map, "booking number")
    total_price = _lookup_value(label_map, "total price", "price")
    excursion = _lookup_value(label_map, "excursion", "tour")
    cruise_date = _parse_date(_lookup_value(label_map, "date", "booking date"))
    cruise_time = _parse_time(_lookup_value(label_map, "time", "start time"))
    num_adults = _parse_num_adults(_lookup_value(label_map, "participants", "participants details", "adults"))
    num_children = _parse_num_children(_lookup_value(label_map, "participants", "participants details", "children"))
    template_language, language_warning = _resolve_template_language(preferred_language)
    gyg_match = re.search(r"\bGYG[A-Z0-9]+\b", f"{notes_block}\n{text_body}", flags=re.IGNORECASE)

    result = BookingParseResult(
        cruise_date=cruise_date,
        cruise_time=cruise_time,
        excursion=excursion,
        booking_type=detect_booking_type(subject, excursion, cruise_date, cruise_time, notes_block, hotel_name_field, bus_stop_field),
        num_adults=num_adults,
        num_children=num_children,
        booking_number=booking_number,
        total_price=total_price,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        preferred_language=preferred_language,
        template_language=template_language,
        notes_block=notes_block,
        hotel_name_field=hotel_name_field,
        bus_stop_field=bus_stop_field,
        raw_customer_name_extraction=raw_customer_name_extraction,
        gyg_ref=gyg_match.group(0).upper() if gyg_match else "",
        warning_note=language_warning,
    )

    notes_hotel = _extract_notes_hotel(notes_block)
    if notes_hotel:
        result.raw_hotel_extraction = notes_hotel
        result.extraction_source = "notes_hotel_field"
    else:
        freeform_name = _extract_notes_freeform_hotel(notes_block)
        if freeform_name:
            result.raw_hotel_extraction = _clean_hotel_candidate(freeform_name)
            result.extraction_source = "notes_freeform"
        elif hotel_name_field and not _is_invalid_hotel_field(hotel_name_field):
            result.raw_hotel_extraction = _clean_hotel_candidate(hotel_name_field)
            result.extraction_source = "options_field"
        else:
            result.extraction_source = "failed"

    if result.booking_type == "OBZOR":
        result.city_name = "Obzor"
    elif result.booking_type == "POMORIE":
        result.city_name = "Pomorie"
    elif result.booking_type in {"ANASTASIA", "SUNSET", "AFTERNOON", "MORNING"}:
        result.city_name = "Sunny Beach"
    else:
        result.city_name = detect_city_name(notes_block, result.raw_hotel_extraction, hotel_name_field, bus_stop_field, excursion)
    return result


def _city_from_result_or_text(db: Session, parsed: BookingParseResult, *texts: str) -> City | None:
    if parsed.city_name:
        return db.query(City).filter(City.name == parsed.city_name).first()
    return detect_city_from_text(db, *texts)


def extract_hotel(db: Session, body: str, threshold: int, city: City | None = None, raw_hotel_name: str = "") -> tuple[Hotel | None, float]:
    """Find the best hotel mention using fuzzy matching, scoped by city when possible."""

    candidate_text = _normalize_spaces(raw_hotel_name or body).lower()
    normalized_body = re.sub(r"\s+", " ", (body or "").lower())
    hotels_query = db.query(Hotel)
    if city:
        hotels_query = hotels_query.filter(Hotel.city_id == city.id)

    if _normalize_token(raw_hotel_name) in {"aluasoul sunny beach", "aluasoul"}:
        fallback_hotel = db.query(Hotel).filter(Hotel.name == "Best Western / Sveshest").first()
        if fallback_hotel:
            return fallback_hotel, 100.0

    best_hotel: Hotel | None = None
    best_score = 0.0
    for hotel in hotels_query.all():
        for candidate in _hotel_candidates(hotel):
            candidate_lower = candidate.lower()
            partial = fuzz.partial_ratio(candidate_lower, candidate_text)
            token = fuzz.token_set_ratio(candidate_lower, candidate_text)
            body_partial = fuzz.partial_ratio(candidate_lower, normalized_body)
            score = max(partial, token, body_partial)
            if score > best_score:
                best_hotel = hotel
                best_score = score

    if best_score >= threshold:
        return best_hotel, best_score
    return None, best_score


def classify_email(
    db: Session,
    subject: str,
    body: str,
    threshold: int,
    html_body: str = "",
    fallback_sender: str = "",
    fallback_name: str = "",
) -> ClassificationResult:
    booking_email = is_booking_email(subject, body)
    booking = parse_booking_email(subject, body, html_body, fallback_sender, fallback_name) if booking_email else BookingParseResult()

    if booking.booking_type == "OBZOR":
        city = db.query(City).filter(City.name == "Obzor").first()
    elif booking.booking_type == "POMORIE":
        city = db.query(City).filter(City.name == "Pomorie").first()
    elif booking.booking_type in {"ANASTASIA", "SUNSET", "AFTERNOON", "MORNING"}:
        city = db.query(City).filter(City.name == "Sunny Beach").first()
    else:
        city = _city_from_result_or_text(db, booking, body, subject, booking.raw_hotel_extraction, booking.notes_block)

    if not city and booking.raw_hotel_extraction:
        hotel_any_city, _ = extract_hotel(db, body=body, threshold=threshold, city=None, raw_hotel_name=booking.raw_hotel_extraction)
        if hotel_any_city and hotel_any_city.city:
            city = hotel_any_city.city

    language = booking.template_language if booking_email else detect_language(body or subject)
    bus_request = is_bus_stop_email(subject, body)
    hotel, score = extract_hotel(
        db,
        body=body,
        threshold=threshold,
        city=city,
        raw_hotel_name=booking.raw_hotel_extraction,
    ) if bus_request else (None, 0.0)

    warning_parts = [booking.warning_note] if booking.warning_note else []
    special_flag = COMMERCIAL_VENUE_FLAGS.get(_normalize_token(booking.raw_hotel_extraction))
    if special_flag:
        hotel = None
        score = 0.0
        warning_parts.append(special_flag)
    if booking_email and not booking.raw_hotel_extraction:
        warning_parts.append("No hotel found in booking")
    if booking_email and not booking.booking_type:
        booking.booking_type = "UNKNOWN"
        warning_parts.append("Could not determine booking type from subject or excursion field")
    if booking_email and not city:
        warning_parts.append("City could not be determined")
    warning_note = "\n".join(part for part in warning_parts if part).strip()
    if warning_note:
        logger.warning("[PARSER] %s", warning_note.replace("\n", " | "))

    return ClassificationResult(
        language=language,
        matched_hotel=hotel,
        score=score,
        is_bus_request=bus_request,
        is_booking_email=booking_email,
        booking_type=booking.booking_type,
        cruise_date=booking.cruise_date,
        cruise_time=booking.cruise_time,
        num_adults=booking.num_adults,
        num_children=booking.num_children,
        booking_number=booking.booking_number,
        total_price=booking.total_price,
        customer_name=booking.customer_name or fallback_name or "Guest",
        customer_email=booking.customer_email or fallback_sender,
        customer_phone=booking.customer_phone,
        raw_customer_name_extraction=booking.raw_customer_name_extraction,
        raw_hotel_extraction=booking.raw_hotel_extraction,
        extraction_source=booking.extraction_source,
        city=city,
        gyg_ref=booking.gyg_ref,
        warning_note=warning_note,
    )
