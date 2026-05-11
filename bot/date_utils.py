"""Date parsing utilities."""

from datetime import datetime, timedelta


def parse_flexible_date(date_str: str) -> str:
    """Parse a date string in several formats and return ``YYYY-MM-DD``.

    Accepted formats:
    * ``YYYY-MM-DD``
    * ``MM-DD``  (current year assumed)
    * ``DD/MM``  (current year assumed)
    * ``DD/MM/YYYY``

    Raises ``ValueError`` if the string cannot be parsed, the date is in the
    past, or it is more than two years in the future.
    """
    current_year = datetime.now().year
    today = datetime.now().date()
    parsed_date = None

    for fmt, s in [
        ('%Y-%m-%d', date_str),
        ('%d/%m/%Y', date_str),
        ('%m-%d',    date_str),
        ('%d/%m',    date_str),
    ]:
        try:
            parsed_date = datetime.strptime(s, fmt).date()
            if fmt in ('%m-%d', '%d/%m'):
                parsed_date = parsed_date.replace(year=current_year)
            break
        except ValueError:
            continue

    if not parsed_date:
        raise ValueError(f"Formato de data inválido: {date_str}")

    if parsed_date < today:
        raise ValueError(
            f"Data já passou: {parsed_date.strftime('%d/%m/%Y')}. "
            "Por favor, use uma data atual ou futura."
        )

    max_future = today + timedelta(days=730)
    if parsed_date > max_future:
        raise ValueError(
            f"Data muito distante: {parsed_date.strftime('%d/%m/%Y')}. "
            f"Máximo de 2 anos no futuro ({max_future.strftime('%d/%m/%Y')})."
        )

    return parsed_date.strftime('%Y-%m-%d')
