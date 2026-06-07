from __future__ import annotations

from pathlib import Path
import re

from cruise_email_dashboard.database.models import EmailLog, VehicleType

REPLIES_DIR = Path(__file__).resolve().parents[1] / "templates" / "replies"
SUPPORTED_LANGUAGES = {"en", "es", "fr", "de", "it", "el"}
MISSING_PICKUP_TIME_PLACEHOLDER = "[PICKUP TIME NOT FOUND]"
HOTEL_REQUEST_WARNING = "No hotel provided by customer"
OLD_NESSEBAR_PORT_VARIANT = "old_nessebar_port"
PICKUP_ADJUSTMENT_COPY = {
    "en": "We would like to offer to pick you up from a pickup point closer to {hotel_name}.",
    "es": "Nos gustaria ofrecerle recogerle desde un punto de recogida mas cercano a {hotel_name}.",
    "fr": "Nous souhaiterions vous proposer une prise en charge depuis un point plus proche de {hotel_name}.",
    "de": "Wir moechten Ihnen eine Abholung von einem naeher bei {hotel_name} gelegenen Treffpunkt anbieten.",
    "it": "Desideriamo offrirle un punto di prelievo piu vicino a {hotel_name}.",
    "el": "Tha thelame na sas prosferoume paralavi apo simeio pio konta sto {hotel_name}.",
}
OLD_NESSEBAR_PORT_TEMPLATES = {
    "en": """Dear {customer_name},

We thank you for your booking for {cruise_date}, {cruise_day}, {booking_type}, for {num_adults}!

As you have selected the Passenger Terminal in Old Nessebar, please make your way directly to the port in the Old Town of Nessebar. Our team will be there to meet you.

We kindly ask you to reply to this email to confirm this arrangement.

Kind Regards,
VIP Catamaran
""",
    "es": """Estimado/a {customer_name},

Le agradecemos su reserva para {cruise_date}, {cruise_day}, {booking_type}, para {num_adults}!

Como ha seleccionado la Terminal de Pasajeros en el casco antiguo de Nessebar, por favor dirijase directamente al puerto en el casco antiguo de Nessebar. Nuestro equipo estara alli para recibirle.

Le rogamos que responda a este correo para confirmar este arreglo.

Saludos cordiales,
VIP Catamaran
""",
    "fr": """Cher/Chere {customer_name},

Nous vous remercions pour votre reservation du {cruise_date}, {cruise_day}, {booking_type}, pour {num_adults}!

Comme vous avez selectionne le terminal passagers du vieux Nessebar, veuillez vous rendre directement au port dans la vieille ville de Nessebar. Notre equipe sera sur place pour vous accueillir.

Nous vous prions de repondre a cet e-mail pour confirmer cette organisation.

Cordialement,
VIP Catamaran
""",
    "de": """Sehr geehrte/r {customer_name},

Vielen Dank fuer Ihre Buchung am {cruise_date}, {cruise_day}, {booking_type}, fuer {num_adults}!

Da Sie das Passenger Terminal in der Altstadt von Nessebar gewaehlt haben, begeben Sie sich bitte direkt zum Hafen in der Altstadt von Nessebar. Unser Team wird Sie dort empfangen.

Bitte antworten Sie auf diese E-Mail, um diese Regelung zu bestaetigen.

Mit freundlichen Gruessen
VIP Catamaran
""",
    "it": """Gentile {customer_name},

La ringraziamo per la sua prenotazione per {cruise_date}, {cruise_day}, {booking_type}, per {num_adults}!

Poiche ha selezionato il Terminal Passeggeri della Citta Vecchia di Nessebar, la preghiamo di recarsi direttamente al porto nel centro storico di Nessebar. Il nostro team sara li per accoglierla.

La preghiamo di rispondere a questa e-mail per confermare questa disposizione.

Cordiali saluti,
VIP Catamaran
""",
    "el": """Agapite/i {customer_name},

Sas efcharistoume gia tin kratisi sas gia {cruise_date}, {cruise_day}, {booking_type}, gia {num_adults}!

Kathos echete epilexei to Passenger Terminal stin Palia Nesebar, sas parakaloume na katefthyntheite apeutheias sto limani stin Palia Poli tis Nesebar. I omada mas tha einai ekei gia na sas ypodechthei.

Sas parakaloume na apantisete se auto to email gia na epivevaiosete afti tin arrangi.

Me ektimisi,
VIP Catamaran
""",
}


def available_template_files() -> list[Path]:
    return sorted(REPLIES_DIR.glob("*.txt"))


def _template_variant(email_log: EmailLog) -> str:
    if HOTEL_REQUEST_WARNING in (email_log.warning_note or ""):
        return "hotel_request"
    if email_log.extraction_source == "old_nessebar_port":
        return OLD_NESSEBAR_PORT_VARIANT
    stop = email_log.assigned_bus_stop
    city_name = stop.city.name if stop and stop.city else ""
    vehicle_type = stop.vehicle_type if stop else VehicleType.doubledecker
    if city_name == "Obzor":
        return "obzor"
    if city_name == "Pomorie":
        return "pomorie"
    if vehicle_type == VehicleType.minibus:
        return "sunny_beach_minibus"
    return "sunny_beach_doubledecker"


def template_path(variant: str, language: str) -> Path:
    if variant == "hotel_request":
        return REPLIES_DIR / f"{language}_hotel_request.txt"
    return REPLIES_DIR / f"{variant}_{language}.txt"


def load_template(variant: str, language: str) -> tuple[str, str, str]:
    """Load the variant/language reply template with a safe English fallback.

    Templates are stored as plain text files so admin edits take effect immediately.
    Each generated reply therefore reads the file fresh from disk and falls back to the
    English version of the same variant if the requested translation is missing.
    """

    requested = (language or "en").lower()
    fallback_note = ""
    if variant == OLD_NESSEBAR_PORT_VARIANT:
        if requested not in OLD_NESSEBAR_PORT_TEMPLATES:
            fallback_note = f"Template for '{variant}/{requested}' not found; fell back to English."
            requested = "en"
        return OLD_NESSEBAR_PORT_TEMPLATES[requested], requested, fallback_note
    if requested not in SUPPORTED_LANGUAGES or not template_path(variant, requested).exists():
        fallback_note = f"Template for '{variant}/{requested}' not found; fell back to English."
        requested = "en"
    return template_path(variant, requested).read_text(encoding="utf-8"), requested, fallback_note


def _booking_type_label(email_log: EmailLog) -> str:
    labels = {
        "MORNING": "Morning VIP Catamaran",
        "AFTERNOON": "Afternoon VIP Catamaran",
        "SUNSET": "Sunset Cruise - VIP Catamaran",
        "ANASTASIA": "Anastasia",
        "OBZOR": "Obzor & Old Nessebar VIP Catamaran",
        "POMORIE": "Pomorie VIP Catamaran",
    }
    return labels.get(email_log.booking_type, email_log.booking_type or "VIP Catamaran")


def _format_context(email_log: EmailLog) -> dict[str, str]:
    stop = email_log.assigned_bus_stop
    hotel = email_log.detected_hotel
    cruise_date = email_log.cruise_date.strftime("%d %B %Y") if email_log.cruise_date else "your cruise date"
    cruise_day = email_log.cruise_date.strftime("%A") if email_log.cruise_date else "scheduled day"
    language = (email_log.detected_language or "en").lower()
    return {
        "customer_name": email_log.sender_name or "Guest",
        "cruise_date": cruise_date,
        "cruise_day": cruise_day,
        "booking_type": _booking_type_label(email_log),
        "num_adults": str(email_log.num_adults or ""),
        "hotel_name": hotel.name if hotel else email_log.raw_hotel_extraction or "your hotel",
        "bus_stop_name": stop.name if stop else "",
        "bus_stop_address": stop.address if stop else "",
        "bus_stop_description": stop.description if stop and stop.description else (stop.name if stop else ""),
        "pickup_adjustment_paragraph": _pickup_adjustment_paragraph(email_log, language),
        "pickup_time": email_log.pickup_time_text or MISSING_PICKUP_TIME_PLACEHOLDER,
        "maps_url": stop.maps_url if stop and stop.maps_url else "",
        "company_name": "VIP Catamaran",
        "company_email": "bookings@vipcatamaran.com",
        "company_phone": "",
        "support_contact_info": "bookings@vipcatamaran.com",
    }


def _pickup_adjustment_paragraph(email_log: EmailLog, language: str) -> str:
    if email_log.extraction_source != "customer_selected_stop":
        return ""
    hotel = email_log.detected_hotel
    if not hotel or not hotel.bus_stop_id or not email_log.assigned_bus_stop_id:
        return ""
    if hotel.bus_stop_id == email_log.assigned_bus_stop_id:
        return ""
    template = PICKUP_ADJUSTMENT_COPY.get(language, PICKUP_ADJUSTMENT_COPY["en"])
    return template.format(hotel_name=hotel.name)


def _clean_rendered_reply(reply: str) -> str:
    cleaned = reply.replace("\r\n", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def build_reply(email_log: EmailLog) -> tuple[str, str, str]:
    template, chosen_language, warning_note = load_template(_template_variant(email_log), email_log.detected_language)
    return _clean_rendered_reply(template.format(**_format_context(email_log))), chosen_language, warning_note


def regenerate_email_draft(email_log: EmailLog) -> None:
    """Rebuild the outbound draft using the correct city and vehicle template family.

    Keeping reply generation centralized matters more now because different resorts use
    different instructions, different vehicles, and even different operational rules.
    Reusing this helper ensures manual reassignment in the UI produces the same style of
    reply as automatic processing during IMAP polling.
    """

    stop = email_log.assigned_bus_stop
    variant = _template_variant(email_log)
    if not stop and variant != "hotel_request":
        email_log.draft_reply = ""
        return
    reply, template_language, warning_note = build_reply(email_log)
    email_log.draft_reply = reply
    email_log.template_language = template_language
    email_log.warning_note = "\n".join(part for part in [email_log.warning_note, warning_note] if part).strip()
