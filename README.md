# Emergency Healthcare Responder System

Web-based prototype that connects **users, hospitals and blood donors** during medical emergencies.
Built with **Python + Flask**, **SQLite** and **Leaflet / OpenStreetMap** (interactive map).

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 . The database (`ehrs.db`) and demo data are created automatically on the first run.
To reset everything, stop the app and delete `ehrs.db`.

> Allow **location access** in the browser when asked (needed for the SOS button and nearby hospitals).
> Map tiles need an internet connection; everything else works offline.

## Demo logins (password for all: `demo123`)

| Role | Email |
|------|-------|
| User (B+) | user1@demo.com |
| User (O+) | user2@demo.com |
| User (B+) | user3@demo.com |
| User (A+) | user4@demo.com |
| Hospital | hospital1@demo.com ... hospital5@demo.com |

Hospitals and their coordinates in the demo data are **fictional** (placed around Faridabad). Register a new hospital from the Register page to add your own.

## Quick demo script

1. Open two browser windows (or one normal + one private). Log in as `user1@demo.com` in one and `hospital1@demo.com` / `hospital2@demo.com` in the other.
2. **User:** press the red **SOS** button (floating on every page), choose the emergency type, press *Send SOS now*.
3. **Hospital:** the alert appears within ~5 seconds with a beep. Press *Acknowledge*, then *Dispatch ambulance*.
4. **User:** the alert page updates live (Alert sent -> Hospital responding -> Ambulance dispatched).
5. **Hospital:** under *Blood requests* post "2 units of B+, Critical". **User** `user1` / `user3` get a notification, open *Blood requests* and press *I am available*. The hospital dashboard lists the donor with a phone number.

## Features (as in the synopsis)

| Synopsis feature | Where |
|------------------|-------|
| User registration, login, profile, blood group | `/register`, `/login`, `/profile` |
| Hospital registration and secure login | `/register?role=hospital` |
| Hospital discovery on interactive map | Home page, `/hospitals` |
| **Emergency (SOS) Button** with location + emergency details | floating button on all user pages, `POST /sos` |
| Alert to nearby registered hospitals | nearest 3 hospitals (within 25 km, else nearest 3); if all decline, forwarded to the next nearest |
| Hospital dashboard: view alert, location, details | `/hospital` (auto-refresh every 5 s) |
| Ambulance assistance coordination | Acknowledge / Dispatch ambulance / Mark resolved (uses ambulance count) |
| Urgent blood requests by hospitals | `/hospital` -> Blood requests |
| Donor notifications and responses | `/blood`, notifications page |
| Hospital dashboard shows donor responses | request cards on `/hospital` |

## Project structure

```
app.py              all routes, database schema, demo data
templates/          HTML pages (Jinja2)
static/style.css    styling
static/app.js       map helpers, SOS modal, location picker
static/vendor/      Leaflet (bundled, so the app also works without a CDN)
requirements.txt
```

### Database tables

`users`, `hospitals`, `alerts`, `alert_hospitals` (which hospitals got which alert and their status),
`blood_requests`, `donor_responses`, `notifications`.

## Security notes

- Passwords are stored hashed (Werkzeug), never as plain text.
- CSRF token on every POST; all SQL uses parameters; templates auto-escape text.
- Users can only see their own alerts; only hospital accounts can open the hospital dashboard.
- For any real deployment set a strong `SECRET_KEY` environment variable and run behind HTTPS (browsers only share location on HTTPS or localhost).

## Limitations (prototype)

- Alerts and notifications are in-app (page auto-refresh). SMS/push is future scope.
- No live ambulance tracking, bed booking or blood-bank integration.
- Not a replacement for calling 112 / 108 in a real emergency.
