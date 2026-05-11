"""JSON persistence for appointments and sent-reminder tracking."""

import json
from pathlib import Path

# Resolve data directory: /data in Docker, ../data when running locally
DATA_DIR = Path('/data') if Path('/data').exists() else Path('../data')
DATA_DIR.mkdir(parents=True, exist_ok=True)

APPOINTMENTS_FILE   = DATA_DIR / 'appointments.json'
SENT_REMINDERS_FILE = DATA_DIR / 'sent_reminders.json'


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

def load_appointments() -> dict:
    """Return the full appointments document, or an empty scaffold."""
    if APPOINTMENTS_FILE.exists():
        with APPOINTMENTS_FILE.open('r', encoding='utf-8') as fh:
            return json.load(fh)
    return {'appointments': []}


def save_appointments(data: dict) -> None:
    """Persist *data* to the appointments file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with APPOINTMENTS_FILE.open('w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Sent-reminder tracking
# ---------------------------------------------------------------------------

def _load_sent_reminders() -> dict:
    if SENT_REMINDERS_FILE.exists():
        with SENT_REMINDERS_FILE.open('r', encoding='utf-8') as fh:
            return json.load(fh)
    return {'reminders': []}


# Public alias used by tests
load_sent_reminders = _load_sent_reminders


def was_reminder_sent(appointment_id: int, occurrence_date: str, reminder_type: str) -> bool:
    """Return True if this specific reminder has already been sent."""
    data = _load_sent_reminders()
    key = f"{appointment_id}_{occurrence_date}_{reminder_type}"
    return key in data['reminders']


def save_sent_reminder_occurrence(
    appointment_id: int, occurrence_date: str, reminder_type: str
) -> None:
    """Record that a reminder was sent, deduplicating by key."""
    data = _load_sent_reminders()
    key  = f"{appointment_id}_{occurrence_date}_{reminder_type}"
    if key not in data['reminders']:
        data['reminders'].append(key)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with SENT_REMINDERS_FILE.open('w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
