"""Scheduled reminder dispatcher: 24 h and 2 h alerts per user."""

from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application

from recurrence import generate_occurrences
from storage import load_appointments, save_sent_reminder_occurrence, was_reminder_sent

_app: Application | None = None


async def check_and_send_reminders() -> None:
    """Scan all appointments and dispatch pending 24 h / 2 h reminders."""
    if not _app:
        return

    try:
        data = load_appointments()
        now  = datetime.now()

        for apt in data.get('appointments', []):
            user_id = apt.get('user_id')
            if not user_id:
                continue

            apt_dt = datetime.strptime(f"{apt['date']} {apt['time']}", '%Y-%m-%d %H:%M')
            if not apt.get('recurrence') and apt_dt <= now:
                continue

            apt_id    = apt['id']
            item_type = "📅 Evento" if apt.get('type') == 'appointment' else "⏰ Lembrete"

            window_start = now - timedelta(hours=24, minutes=11)
            window_end   = now + timedelta(hours=24, minutes=11)

            try:
                for occ_date, occ_time in generate_occurrences(apt, from_dt=window_start, to_dt=window_end):
                    occ_dt     = datetime.strptime(f"{occ_date} {occ_time}", '%Y-%m-%d %H:%M')
                    time_until = occ_dt - now
                    if occ_dt <= now:
                        continue

                    # 24-hour reminder
                    if timedelta(hours=23, minutes=50) <= time_until <= timedelta(hours=24, minutes=10):
                        if not was_reminder_sent(apt_id, occ_date, '24h'):
                            msg = _build_message(apt, occ_dt, occ_time, item_type,
                                                 when="AMANHÃ", hours_label="24 horas")
                            await _app.bot.send_message(chat_id=user_id, text=msg)
                            save_sent_reminder_occurrence(apt_id, occ_date, '24h')
                            print(f"Sent 24h reminder for apt {apt_id} ({occ_date}) → user {user_id}")

                    # 2-hour reminder
                    elif timedelta(hours=1, minutes=50) <= time_until <= timedelta(hours=2, minutes=10):
                        if not was_reminder_sent(apt_id, occ_date, '2h'):
                            msg = _build_message(apt, occ_dt, occ_time, item_type,
                                                 when="EM 2 HORAS", hours_label="2 horas", today=True)
                            await _app.bot.send_message(chat_id=user_id, text=msg)
                            save_sent_reminder_occurrence(apt_id, occ_date, '2h')
                            print(f"Sent 2h reminder for apt {apt_id} ({occ_date}) → user {user_id}")

            except Exception as exc:
                print(f"Error processing appointment {apt_id}: {exc}")

    except Exception as exc:
        print(f"Error in check_and_send_reminders: {exc}")


def _build_message(
    apt: dict,
    occ_dt: datetime,
    occ_time: str,
    item_type: str,
    when: str,
    hours_label: str,
    today: bool = False,
) -> str:
    date_str = "HOJE" if today else occ_dt.strftime('%d/%m/%Y')
    lines = [f"🔔 {item_type} {when}!\n", f"Data: {date_str} às {occ_time}"]
    if apt.get('doctor'):
        lines.append(f"Título: {apt['doctor']}")
    lines.append(f"Descrição: {apt['description']}")
    if apt.get('location'):
        lines.append(f"Local: {apt['location']}")
    lines.append(f"\n⏰ Faltam aproximadamente {hours_label}!")
    return '\n'.join(lines)


async def post_init(application: Application) -> None:
    """Attach the application instance and start the APScheduler job."""
    global _app
    _app = application

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_send_reminders,
        trigger=IntervalTrigger(minutes=5),
        id='reminder_checker',
        name='Check and send appointment reminders',
        replace_existing=True,
    )
    scheduler.start()

    print("🔔 Automatic reminder system activated!")
    print("📱 Each user will receive reminders for their own appointments")
    print("⏰ Checking for reminders every 5 minutes...")
