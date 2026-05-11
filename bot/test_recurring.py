#!/usr/bin/env python3
"""
Unit tests for recurring event logic in bot.py.
Run with: python -m pytest test_recurring.py -v
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Import only the pure functions from bot.py without triggering the
# module-level credential checks (BOT_TOKEN validation etc.)
# ---------------------------------------------------------------------------
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test_token')
os.environ.setdefault('OPENAI_API_KEY', '')

# Patch the credential guard so it doesn't raise on import
with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'fake_token_for_tests'}):
    # We import only specific names to avoid Telegram/OpenAI network calls
    import importlib, types

    # Stub heavy third-party modules before importing bot
    for mod in ['telegram', 'telegram.ext', 'openai', 'apscheduler',
                'apscheduler.schedulers.asyncio', 'apscheduler.triggers.interval']:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    # Minimal stubs so bot.py attribute accesses don't fail
    sys.modules['telegram'].Update = object
    sys.modules['telegram.ext'].Application = object
    sys.modules['telegram.ext'].CommandHandler = lambda *a, **kw: None
    sys.modules['telegram.ext'].MessageHandler = lambda *a, **kw: None
    sys.modules['telegram.ext'].filters = MagicMock()
    sys.modules['telegram.ext'].ContextTypes = MagicMock()
    sys.modules['openai'].OpenAI = MagicMock()
    sys.modules['apscheduler.schedulers.asyncio'].AsyncIOScheduler = MagicMock()
    sys.modules['apscheduler.triggers.interval'].IntervalTrigger = MagicMock()

    # Patch the token guard
    with patch('builtins.open', unittest.mock.mock_open(read_data='{}')):
        with patch('os.path.exists', return_value=False):
            import bot as bot_module

# Pull the functions under test
_add_months = bot_module._add_months
get_recurrence_end = bot_module.get_recurrence_end
iter_occurrences = bot_module.iter_occurrences
FREQ_LABELS = bot_module.FREQ_LABELS
FREQ_ALIASES = bot_module.FREQ_ALIASES


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAddMonths(unittest.TestCase):

    def test_simple_add(self):
        dt = datetime(2026, 1, 15)
        result = _add_months(dt, 1)
        self.assertEqual(result, datetime(2026, 2, 15))

    def test_clamps_to_last_day(self):
        dt = datetime(2026, 1, 31)
        result = _add_months(dt, 1)
        self.assertEqual(result, datetime(2026, 2, 28))

    def test_year_rollover(self):
        dt = datetime(2026, 12, 1)
        result = _add_months(dt, 2)
        self.assertEqual(result, datetime(2027, 2, 1))

    def test_multiple_months(self):
        dt = datetime(2026, 3, 10)
        result = _add_months(dt, 6)
        self.assertEqual(result, datetime(2026, 9, 10))


class TestGetRecurrenceEnd(unittest.TestCase):

    def test_weekly_ends_in_12_months(self):
        start = datetime(2026, 5, 14, 15, 0)
        end = get_recurrence_end(start, 'weekly')
        self.assertEqual(end, _add_months(start, 12))

    def test_monthly_ends_in_12_months(self):
        start = datetime(2026, 5, 1, 10, 0)
        end = get_recurrence_end(start, 'monthly')
        self.assertEqual(end, _add_months(start, 12))

    def test_yearly_ends_in_2_years(self):
        start = datetime(2026, 5, 1, 10, 0)
        end = get_recurrence_end(start, 'yearly')
        self.assertEqual(end, start.replace(year=2028))

    def test_biweekly_ends_in_12_months(self):
        start = datetime(2026, 6, 1, 8, 0)
        end = get_recurrence_end(start, 'biweekly')
        self.assertEqual(end, _add_months(start, 12))


class TestIterOccurrences(unittest.TestCase):

    def _make_apt(self, date, time, recurrence=None, recurrence_end=None):
        apt = {
            'id': 1,
            'date': date,
            'time': time,
        }
        if recurrence:
            apt['recurrence'] = recurrence
            apt['recurrence_end'] = recurrence_end or get_recurrence_end(
                datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M'), recurrence
            ).strftime('%Y-%m-%d')
        return apt

    # --- Non-recurring ---

    def test_non_recurring_yields_single(self):
        apt = self._make_apt('2026-05-20', '10:00')
        result = list(iter_occurrences(apt))
        self.assertEqual(result, [('2026-05-20', '10:00')])

    # --- Weekly ---

    def test_weekly_first_occurrence(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly')
        result = list(iter_occurrences(apt))
        self.assertEqual(result[0], ('2026-05-14', '15:00'))
        self.assertEqual(result[1], ('2026-05-21', '15:00'))

    def test_weekly_count(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-06-04')
        result = list(iter_occurrences(apt))
        # 14, 21, 28 May, 4 Jun = 4 occurrences
        self.assertEqual(len(result), 4)

    def test_weekly_days_apart(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-05-28')
        dates = [r[0] for r in iter_occurrences(apt)]
        for i in range(1, len(dates)):
            d0 = datetime.strptime(dates[i - 1], '%Y-%m-%d')
            d1 = datetime.strptime(dates[i], '%Y-%m-%d')
            self.assertEqual((d1 - d0).days, 7)

    # --- Biweekly ---

    def test_biweekly_gap(self):
        apt = self._make_apt('2026-05-14', '09:00', 'biweekly',
                             recurrence_end='2026-06-11')
        dates = [r[0] for r in iter_occurrences(apt)]
        for i in range(1, len(dates)):
            d0 = datetime.strptime(dates[i - 1], '%Y-%m-%d')
            d1 = datetime.strptime(dates[i], '%Y-%m-%d')
            self.assertEqual((d1 - d0).days, 14)

    # --- Monthly ---

    def test_monthly_increments_month(self):
        apt = self._make_apt('2026-05-14', '10:00', 'monthly',
                             recurrence_end='2026-08-14')
        dates = [r[0] for r in iter_occurrences(apt)]
        self.assertEqual(dates, ['2026-05-14', '2026-06-14', '2026-07-14', '2026-08-14'])

    def test_monthly_clamps_end_of_month(self):
        apt = self._make_apt('2026-01-31', '10:00', 'monthly',
                             recurrence_end='2026-03-31')
        dates = [r[0] for r in iter_occurrences(apt)]
        self.assertIn('2026-02-28', dates)

    # --- Yearly ---

    def test_yearly_increments_year(self):
        apt = self._make_apt('2026-05-14', '10:00', 'yearly',
                             recurrence_end='2028-05-14')
        dates = [r[0] for r in iter_occurrences(apt)]
        self.assertEqual(dates, ['2026-05-14', '2027-05-14', '2028-05-14'])

    # --- Window filtering ---

    def test_from_dt_filters_past(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-06-04')
        from_dt = datetime(2026, 5, 22)  # after first two occurrences
        result = list(iter_occurrences(apt, from_dt=from_dt))
        for date_str, _ in result:
            self.assertGreaterEqual(
                datetime.strptime(date_str, '%Y-%m-%d'), from_dt
            )

    def test_to_dt_filters_future(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-07-14')
        to_dt = datetime(2026, 5, 28)
        result = list(iter_occurrences(apt, to_dt=to_dt))
        for date_str, _ in result:
            self.assertLessEqual(
                datetime.strptime(date_str, '%Y-%m-%d'), to_dt
            )

    def test_window_both_bounds(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-07-14')
        from_dt = datetime(2026, 5, 20)
        to_dt = datetime(2026, 6, 3)
        result = list(iter_occurrences(apt, from_dt=from_dt, to_dt=to_dt))
        self.assertEqual(len(result), 2)  # 21 May, 28 May
        self.assertEqual(result[0][0], '2026-05-21')
        self.assertEqual(result[1][0], '2026-05-28')

    def test_window_empty(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-06-04')
        # Window entirely before start
        result = list(iter_occurrences(apt, to_dt=datetime(2026, 5, 1)))
        self.assertEqual(result, [])


class TestFreqAliases(unittest.TestCase):

    def test_portuguese_aliases_resolve(self):
        for alias, expected in [
            ('semanal', 'weekly'),
            ('quinzenal', 'biweekly'),
            ('mensal', 'monthly'),
            ('anual', 'yearly'),
            ('toda semana', 'weekly'),
            ('todo m\u00eas', 'monthly'),
        ]:
            self.assertEqual(FREQ_ALIASES.get(alias), expected, f"Alias '{alias}' failed")

    def test_all_freq_labels_present(self):
        for key in ('weekly', 'biweekly', 'monthly', 'yearly'):
            self.assertIn(key, FREQ_LABELS)


if __name__ == '__main__':
    unittest.main(verbosity=2)
