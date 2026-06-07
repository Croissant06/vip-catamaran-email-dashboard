# VIP Catamaran Email Dashboard

Private operations dashboard for automating booking email handling for VIP Catamaran, Bulgaria.

## What It Does

This app helps a cruise company process booking emails faster and more consistently. It reads incoming booking messages, extracts customer and trip details, matches the hotel to the correct pickup stop, and generates multilingual draft replies for staff to review and send.

The dashboard also gives the team a central place to manage hotels, bus stops, schedules, flagged emails, and historical imports, so day-to-day operations can be handled from one interface instead of across multiple inboxes and spreadsheets.

## Tech Stack

- FastAPI
- SQLAlchemy
- SQLite
- Jinja2
- Tailwind CSS
- APScheduler
- IMAP / SMTP integrations

## Features

- Automated parsing of booking emails from supported booking platforms
- Fuzzy hotel matching against a managed hotel database
- Automatic hotel-to-bus-stop assignment
- Multilingual draft reply generation
- Live dashboard updates and multi-user presence tracking via SSE
- Historical mailbox import with duplicate protection
- Staff hotel management tools for adding new hotels and aliases

## Deployment

- Hetzner VPS
- Caddy reverse proxy
- `systemd` service management
- GitHub Actions CI/CD deployment workflow

## Notes

- Built as a private production app for VIP Catamaran, Bulgaria
- Designed for internal staff use rather than public access
