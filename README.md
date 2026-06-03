# VIP Catamaran Email Dashboard

FastAPI dashboard for VIP Catamaran staff to process booking emails, match hotels to pickup stops, draft multilingual replies, and manage route data for Sunny Beach, Obzor, and Pomorie.

## Features

- IMAP polling for incoming booking emails
- Bookeo / GetYourGuide HTML email parsing
- City-aware hotel matching with `rapidfuzz`
- Booking-type-aware schedule resolution
- Multilingual reply drafting from editable text templates
- FastAPI + Jinja2 admin dashboard
- Leaflet map view for pickup stops
- SSE live inbox notifications
- Admin mailbox status checks for IMAP and SMTP

## Tech Stack

- Python
- FastAPI
- SQLAlchemy
- Jinja2
- SQLite
- Tailwind CSS via CDN
- Chart.js via CDN
- Leaflet via CDN

## Local Setup

1. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

2. Review `.env.example` and create a local `.env`.

3. Seed the database:

```bash
python seed.py
```

4. Run the app:

```bash
uvicorn main:app --reload
```

## Demo Accounts

- `admin` / `admin123`
- `staff` / `staff123`

## Useful Commands

```bash
python manage.py create_admin
python seed.py
```

## Notes

- `.env` is ignored and should stay local.
- SMTP uses SSL on port `465`.
- IMAP uses SSL on port `993`.
- Current mailbox settings are editable from the Admin Panel.

