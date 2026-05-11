"""Recurrence helpers: frequency constants and occurrence generator."""

import calendar
from datetime import datetime, timedelta

FREQ_LABELS: dict[str, str] = {
    'daily':    'diário',
    'weekly':   'semanal',
    'biweekly': 'quinzenal',
    'monthly':  'mensal',
    'yearly':   'anual',
}

FREQ_ALIASES: dict[str, str] = {
    'diário': 'daily', 'diario': 'daily', 'diariamente': 'daily', 'daily': 'daily',
    'todo dia': 'daily', 'todos os dias': 'daily', 'todo o dia': 'daily', 'cada dia': 'daily',
    'semanal': 'weekly', 'semana': 'weekly', 'semanalmente': 'weekly', 'weekly': 'weekly',
    'toda semana': 'weekly', 'todo semana': 'weekly',
    'quinzenal': 'biweekly', 'quinzenalmente': 'biweekly', 'biweekly': 'biweekly',
    'a cada duas semanas': 'biweekly', 'duas semanas': 'biweekly',
    'mensal': 'monthly', 'mensalmente': 'monthly', 'monthly': 'monthly',
    'todo mês': 'monthly', 'todo mes': 'monthly', 'todo o mês': 'monthly',
    'anual': 'yearly', 'anualmente': 'yearly', 'yearly': 'yearly',
    'todo ano': 'yearly', 'todo o ano': 'yearly',
}


def _add_months(dt: datetime, n: int) -> datetime:
    """Add *n* months to *dt*, clamping to the last day of the target month."""
    month = dt.month - 1 + n
    year = dt.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def generate_occurrences(
    apt: dict,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
):
    """Yield ``(date_str, time_str)`` tuples for an appointment rule.

    * Non-recurring entries yield exactly one tuple.
    * Recurring entries are expanded within ``[from_dt, to_dt]``.
    * If *recurrence_end* is absent the series is treated as infinite;
      *to_dt* (or a 50-year safety cap) is used as the upper bound.
    """
    frequency = apt.get('recurrence')
    if not frequency:
        yield apt['date'], apt['time']
        return

    start = datetime.strptime(f"{apt['date']} {apt['time']}", '%Y-%m-%d %H:%M')
    end_str = apt.get('recurrence_end')
    if end_str:
        end = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59)
    elif to_dt:
        end = to_dt
    else:
        end = start.replace(year=start.year + 50)

    current = start
    while current <= end:
        if (from_dt is None or current >= from_dt) and (to_dt is None or current <= to_dt):
            yield current.strftime('%Y-%m-%d'), apt['time']
        if frequency == 'daily':
            current += timedelta(days=1)
        elif frequency == 'weekly':
            current += timedelta(weeks=1)
        elif frequency == 'biweekly':
            current += timedelta(weeks=2)
        elif frequency == 'monthly':
            current = _add_months(current, 1)
        elif frequency == 'yearly':
            current = current.replace(year=current.year + 1)
        else:
            break
