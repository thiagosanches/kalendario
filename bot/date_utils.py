"""Flexible date-string parser."""

from datetime import datetime, timedelta


def parse_flexible_date(date_str: str) -> str:
    """Parse *date_str* and return an ISO ``YYYY-MM-DD`` string.

    Accepted input formats:
    - ``YYYY-MM-DD``
    - ``MM-DD``  (current year assumed)
    - ``DD/MM``  (current year assumed)
    - ``DD/MM/YYYY``

    Raises :class:`ValueError` if the date is in the past or more than
    two years in the future.
    """
    current_year = datetime.now().year
    today = datetime.now().date()
    parsed = None

    for fmt, src in [
        ('%Y-%m-%d', date_str),
        ('%m-%d',    date_str),
        ('%d/%m',    date_str),
        ('%d/%m/%Y', date_str),
    ]:
        try:
            dt = datetime.strptime(src, fmt)
            if fmt in ('%m-%d', '%d/%m'):
                dt = dt.replace(year=current_year)
            parsed = dt.date()
            break
        except ValueError:
            continue

    if parsed is None:
        raise ValueError(f"Formato de data inválido: {date_str}")

    if parsed < today:
        raise ValueError(
            f"Data já passou: {parsed.strftime('%d/%m/%Y')}. "
            "Por favor, use uma data atual ou futura."
        )

    max_future = today + timedelta(days=730)
    if parsed > max_future:
        raise ValueError(
            f"Data muito distante: {parsed.strftime('%d/%m/%Y')}. "
            f"Máximo de 2 anos no futuro ({max_future.strftime('%d/%m/%Y')})."
        )

    return parsed.strftime('%Y-%m-%d')
