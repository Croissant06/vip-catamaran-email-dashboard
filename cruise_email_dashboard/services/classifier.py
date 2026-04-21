from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import re

from bs4 import BeautifulSoup
from langdetect import LangDetectException, detect
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.models import City, Hotel

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
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "greek": "el",
}
CITY_HINTS = {
    "sunny beach": "Sunny Beach",
    "slanchev bryag": "Sunny Beach",
    "slunchev bryag": "Sunny Beach",
    "sveti vlas": "Sunny Beach",
    "nessebar": "Sunny Beach",
    "obzor": "Obzor",
    "pomorie": "Pomorie",
    "pomori": "Pomorie",
}


@dataclass
class BookingParseResult:
    cruise_date: date | None = None
    cruise_time: time | None = None
    excursion: str = ""
    booking_type: str = ""
    num_adults: int | None = None
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
    booking_number: str
    total_price: str
    customer_name: str
    customer_email: str
    customer_phone: str
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


def _build_label_map(html_body: str, text_body: str) -> dict[str, str]:
    """Parse Bookeo's table layout into a simple label/value lookup.

    Booking emails are generated from HTML receipt tables, so BeautifulSoup gives us a
    predictable way to extract each row without brittle string slicing. We then fold the
    result into a case-insensitive dictionary so later parsing code can ask for labels
    like `Date`, `Preferred language`, or `Booking number` directly.
    """

    lookup: dict[str, str] = {}
    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if len(cells) >= 2:
                key = _normalize_spaces(cells[0]).rstrip(":").lower()
                value = _normalize_spaces(cells[1])
                if key and value and key not in lookup:
                    lookup[key] = value

    if text_body:
        for line in text_body.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = _normalize_spaces(key).lower()
            value = _normalize_spaces(value)
            if key and value and key not in lookup:
                lookup[key] = value
    return lookup


def _lookup_value(label_map: dict[str, str], *labels: str) -> str:
    for label in labels:
        value = label_map.get(label.lower())
        if value:
            return value
    return ""


def _parse_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%A, %d %B %Y", "%d %B %Y", "%A %d %B %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value: str) -> time | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    return None


def _parse_num_adults(value: str) -> int | None:
    match = re.search(r"(\d+)\s*adult", value.lower())
    if match:
        return int(match.group(1))
    fallback = re.search(r"\b(\d+)\b", value)
    return int(fallback.group(1)) if fallback else None


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
        if line.lower().startswith("hotel:"):
            continue
        if len(line) > 90:
            continue
        if any(token in line.lower() for token in ("slanchev", "sunny beach", "obzor", "pomorie", "hotel", "resort", "pub", "bay", "palace", "wave", "saint")):
            return line
    return ""


def detect_city_name(*values: str) -> str:
    haystack = " ".join(value for value in values if value).lower()
    for hint, matched_city in CITY_HINTS.items():
        if hint in haystack:
            return matched_city
    return ""


def detect_city_from_text(db: Session, *values: str) -> City | None:
    city_name = detect_city_name(*values)
    if not city_name:
        return None
    return db.query(City).filter(City.name == city_name).first()


def detect_booking_type(subject: str, excursion: str, cruise_date: date | None = None) -> str:
    combined = f"{subject} {excursion}".lower()
    if "anastasia" in combined:
        return "ANASTASIA"
    if "obzor" in combined:
        return "OBZOR"
    if "pomorie" in combined:
        return "POMORIE"
    if "sunset cruise - vip catamaran" in combined or "sunset vip catamaran" in combined or "sunset" in combined:
        return "SUNSET"
    if "afternoon vip catamaran" in combined or "afternoon" in combined:
        return "AFTERNOON"
    if "morning vip catamaran" in combined or "morning" in combined:
        return "MORNING"
    if cruise_date and cruise_date.month == 9:
        return "MORNING"
    return ""


def parse_booking_email(subject: str, text_body: str, html_body: str, fallback_sender: str, fallback_name: str) -> BookingParseResult:
    """Extract structured Bookeo/GetYourGuide booking fields from the booking email.

    The parser deliberately follows the platform's layout rather than guessing from the
    whole message. We read the HTML receipt table first, then fall back to text lines
    when needed, and finally apply the exact hotel extraction priority requested by the
    business rules so staff can understand why a hotel was matched or flagged.
    """

    label_map = _build_label_map(html_body, text_body)
    combined_text = _normalize_spaces(BeautifulSoup(html_body, "html.parser").get_text("\n", strip=True) if html_body else text_body)
    notes_block = _lookup_value(label_map, "notes")
    hotel_name_field = _lookup_value(label_map, "name of your hotel or complex")
    bus_stop_field = _lookup_value(label_map, "choose the pickup point")
    preferred_language = _lookup_value(label_map, "preferred language")
    customer_name = _lookup_value(label_map, "customer", "name", "customer name") or fallback_name or "Guest"
    customer_email = _lookup_value(label_map, "email") or _extract_reply_email(combined_text, fallback_sender)
    customer_phone = _lookup_value(label_map, "phone", "mobile", "phone (mobile)")
    booking_number = _lookup_value(label_map, "booking number")
    total_price = _lookup_value(label_map, "total price")
    excursion = _lookup_value(label_map, "excursion")
    cruise_date = _parse_date(_lookup_value(label_map, "date"))
    cruise_time = _parse_time(_lookup_value(label_map, "time"))
    num_adults = _parse_num_adults(_lookup_value(label_map, "participants"))

    result = BookingParseResult(
        cruise_date=cruise_date,
        cruise_time=cruise_time,
        excursion=excursion,
        booking_type=detect_booking_type(subject, excursion, cruise_date),
        num_adults=num_adults,
        booking_number=booking_number,
        total_price=total_price,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        preferred_language=preferred_language,
        template_language=SUPPORTED_LANGUAGE_MAP.get(preferred_language.lower(), "en") if preferred_language else "en",
        notes_block=notes_block,
        hotel_name_field=hotel_name_field,
        bus_stop_field=bus_stop_field,
        gyg_ref=(re.search(r"\bGYG[A-Z0-9]+\b", f"{notes_block}\n{text_body}", flags=re.IGNORECASE).group(0) if re.search(r"\bGYG[A-Z0-9]+\b", f"{notes_block}\n{text_body}", flags=re.IGNORECASE) else ""),
    )

    if preferred_language and preferred_language.lower() not in SUPPORTED_LANGUAGE_MAP:
        result.warning_note = f"Unsupported language: {preferred_language}, defaulted to EN"

    hotel_line_match = re.search(r"^Hotel:\s*(.+)$", notes_block, flags=re.IGNORECASE | re.MULTILINE)
    if hotel_line_match:
        raw_name = _normalize_spaces(hotel_line_match.group(1))
        result.raw_hotel_extraction = raw_name.split(",")[0].strip()
        result.extraction_source = "notes_hotel_field"
    else:
        freeform_name = _extract_notes_freeform_hotel(notes_block)
        if freeform_name:
            result.raw_hotel_extraction = freeform_name
            result.extraction_source = "notes_freeform"
        elif hotel_name_field and hotel_name_field not in {"(empty)", "Invalid selection"}:
            result.raw_hotel_extraction = hotel_name_field
            result.extraction_source = "options_field"
        else:
            result.extraction_source = "failed"

    result.city_name = detect_city_name(notes_block, result.raw_hotel_extraction, hotel_name_field, excursion)
    return result


def _city_from_result_or_text(db: Session, parsed: BookingParseResult, *texts: str) -> City | None:
    if parsed.city_name:
        return db.query(City).filter(City.name == parsed.city_name).first()
    return detect_city_from_text(db, *texts)


def extract_hotel(db: Session, body: str, threshold: int, city: City | None = None, raw_hotel_name: str = "") -> tuple[Hotel | None, float]:
    """Find the best hotel mention using fuzzy matching, scoped by city when possible.

    City scoping matters for real production data because the same label can exist in
    multiple resorts. For example, "Aqua Paradise" appears in both Sunny Beach traffic
    and Pomorie traffic. We therefore prefer matching against hotels from the detected
    city first, then compare the raw extracted hotel string against each name and alias.
    """

    candidate_text = _normalize_spaces(raw_hotel_name or body).lower()
    normalized_body = re.sub(r"\s+", " ", (body or "").lower())
    hotels_query = db.query(Hotel)
    if city:
        hotels_query = hotels_query.filter(Hotel.city_id == city.id)

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

    city = _city_from_result_or_text(db, booking, body, subject, booking.raw_hotel_extraction, booking.notes_block)
    if booking.raw_hotel_extraction and not city and booking.booking_type == "OBZOR":
        city = db.query(City).filter(City.name == "Obzor").first()
    if booking.raw_hotel_extraction and not city and booking.booking_type == "POMORIE":
        city = db.query(City).filter(City.name == "Pomorie").first()

    language = booking.template_language if booking_email else detect_language(body or subject)
    bus_request = is_bus_stop_email(subject, body)
    hotel, score = extract_hotel(
        db,
        body=body,
        threshold=threshold,
        city=city,
        raw_hotel_name=booking.raw_hotel_extraction,
    ) if bus_request else (None, 0.0)

    warning_note = booking.warning_note
    if booking_email and not booking.raw_hotel_extraction:
        warning_note = "Hotel name not found in booking — manual assignment required"

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
        booking_number=booking.booking_number,
        total_price=booking.total_price,
        customer_name=booking.customer_name or fallback_name or "Guest",
        customer_email=booking.customer_email or fallback_sender,
        customer_phone=booking.customer_phone,
        raw_hotel_extraction=booking.raw_hotel_extraction,
        extraction_source=booking.extraction_source,
        city=city,
        gyg_ref=booking.gyg_ref,
        warning_note=warning_note,
    )
