"""JSON persistence for appointments and sent-reminder tracking."""

import json
import os
from pathlib import Path

# Data directory — /data in Docker, ../data when running locally
DATA_DIR = Path('/data') if Path('/data').exists() else Path('../data')
APPOINTMENTS_FILE = DATA_DIR / 'appointments.json'
SENT_REMINDERS_FILE = DATA_DIR / 'sent_reminders.json'


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

def load_appointments() -> dict:
    """Return the full appointments document, or an empty skeleton."""
    if APPOINTMENTS_FILE.exists():
        with APPOINTMENTS_FILE.open(encoding='utf-8') as f:
            return json.load(f)
    return {"appointments": []}


def save_appointments(data: dict) -> None:
    """Persist the appointments document to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with APPOINTMENTS_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Sent-reminder tracking (per occurrence)
# ---------------------------------------------------------------------------

def _load_sent_reminders() -> dict:
    if SENT_REMINDERS_FILE.exists():
        with SENT_REMINDERS_FILE.open(encoding='utf-8') as f:
            return json.load(f)
    return {"reminders": []}


def _save_sent_reminders(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SENT_REMINDERS_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def was_reminder_sent(appointment_id: int, occurrence_date: str, reminder_type: str) -> bool:
    """Return *True* if this reminder was already dispatched."""
    data = _load_sent_reminders()
    key = f"{appointment_id}_{occurrence_date}_{reminder_type}"
    return key in data['reminders']


def save_sent_reminder_occurrence(
    appointment_id: int,
    occurrence_date: str,
    reminder_type: str,
) -> None:
    """Record that a reminder has been sent so it is not sent again."""
    data = _load_sent_reminders()
    key = f"{appointment_id}_{occurrence_date}_{reminder_type}"
    if key not in data['reminders']:
        data['reminders'].append(key)
        _save_sent_reminders(data)


# Keep old name as alias so legacy callers are not broken
load_sent_reminders = _load_sent_reminders
