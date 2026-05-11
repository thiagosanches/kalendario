#!/usr/bin/env python3
"""
Unit tests for bot.py pure functions.
Run with: python3 -m pytest test_recurring.py -v
"""

import sys
import os
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, mock_open

# ---------------------------------------------------------------------------
# Bootstrap: stub heavy third-party deps so bot.py can be imported without
# a real Telegram token or network connection.
# ---------------------------------------------------------------------------
os.environ['TELEGRAM_BOT_TOKEN'] = 'fake_token_for_tests'
os.environ['OPENAI_API_KEY'] = ''

import types

for mod in ['telegram', 'telegram.ext', 'openai', 'apscheduler',
            'apscheduler.schedulers.asyncio', 'apscheduler.triggers.interval']:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

sys.modules['telegram'].Update = object
sys.modules['telegram.ext'].Application = object
sys.modules['telegram.ext'].CommandHandler = lambda *a, **kw: None
sys.modules['telegram.ext'].MessageHandler = lambda *a, **kw: None
sys.modules['telegram.ext'].filters = MagicMock()
sys.modules['telegram.ext'].ContextTypes = MagicMock()
sys.modules['openai'].OpenAI = MagicMock()
sys.modules['apscheduler.schedulers.asyncio'].AsyncIOScheduler = MagicMock()
sys.modules['apscheduler.triggers.interval'].IntervalTrigger = MagicMock()

with patch('os.path.exists', return_value=False), \
     patch('os.makedirs'), \
     patch('builtins.open', mock_open(read_data='{}')):
    import bot as bot_module

# Pull functions and constants under test
_add_months                  = bot_module._add_months
generate_occurrences         = bot_module.generate_occurrences
parse_flexible_date          = bot_module.parse_flexible_date
load_appointments            = bot_module.load_appointments
save_appointments            = bot_module.save_appointments
load_sent_reminders          = bot_module.load_sent_reminders
was_reminder_sent            = bot_module.was_reminder_sent
save_sent_reminder_occurrence = bot_module.save_sent_reminder_occurrence
is_user_allowed              = bot_module.is_user_allowed
FREQ_LABELS                  = bot_module.FREQ_LABELS
FREQ_ALIASES                 = bot_module.FREQ_ALIASES


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



class TestIterOccurrences(unittest.TestCase):

    def _make_apt(self, date, time, recurrence=None, recurrence_end=None):
        apt = {
            'id': 1,
            'date': date,
            'time': time,
        }
        if recurrence:
            apt['recurrence'] = recurrence
            if recurrence_end:
                apt['recurrence_end'] = recurrence_end
            # No recurrence_end → infinite series
        return apt

    def test_infinite_uses_to_dt_bound(self):
        # No recurrence_end → series is infinite; to_dt caps the results
        apt = self._make_apt('2026-05-14', '15:00', 'weekly')
        to_dt = datetime(2026, 6, 4, 23, 59)
        result = list(generate_occurrences(apt, to_dt=to_dt))
        # 14, 21, 28 May, 4 Jun = 4 occurrences
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0][0], '2026-05-14')
        self.assertEqual(result[-1][0], '2026-06-04')

    def test_infinite_no_to_dt_uses_safety_cap(self):
        # No recurrence_end, no to_dt → safety cap (50 years), just check it doesn't hang
        apt = self._make_apt('2026-05-14', '15:00', 'yearly')
        result = list(generate_occurrences(apt))
        self.assertEqual(len(result), 51)  # 2026 through 2076

    # --- Non-recurring ---

    def test_non_recurring_yields_single(self):
        apt = self._make_apt('2026-05-20', '10:00')
        result = list(generate_occurrences(apt))
        self.assertEqual(result, [('2026-05-20', '10:00')])

    # --- Weekly ---

    def test_weekly_first_occurrence(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly')
        result = list(generate_occurrences(apt))
        self.assertEqual(result[0], ('2026-05-14', '15:00'))
        self.assertEqual(result[1], ('2026-05-21', '15:00'))

    def test_weekly_count(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-06-04')
        result = list(generate_occurrences(apt))
        # 14, 21, 28 May, 4 Jun = 4 occurrences
        self.assertEqual(len(result), 4)

    # --- Daily ---
    def test_daily_count(self):
        apt = self._make_apt('2026-05-11', '13:30', 'daily',
                             recurrence_end='2026-05-17')
        result = list(generate_occurrences(apt))
        # 11,12,13,14,15,16,17 May = 7 occurrences ("por uma semana")
        self.assertEqual(len(result), 7)

    def test_daily_days_apart(self):
        apt = self._make_apt('2026-05-11', '13:30', 'daily',
                             recurrence_end='2026-05-13')
        dates = [r[0] for r in generate_occurrences(apt)]
        self.assertEqual(dates, ['2026-05-11', '2026-05-12', '2026-05-13'])

    def test_weekly_days_apart(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-05-28')
        dates = [r[0] for r in generate_occurrences(apt)]
        for i in range(1, len(dates)):
            d0 = datetime.strptime(dates[i - 1], '%Y-%m-%d')
            d1 = datetime.strptime(dates[i], '%Y-%m-%d')
            self.assertEqual((d1 - d0).days, 7)

    # --- Biweekly ---

    def test_biweekly_gap(self):
        apt = self._make_apt('2026-05-14', '09:00', 'biweekly',
                             recurrence_end='2026-06-11')
        dates = [r[0] for r in generate_occurrences(apt)]
        for i in range(1, len(dates)):
            d0 = datetime.strptime(dates[i - 1], '%Y-%m-%d')
            d1 = datetime.strptime(dates[i], '%Y-%m-%d')
            self.assertEqual((d1 - d0).days, 14)

    # --- Monthly ---

    def test_monthly_increments_month(self):
        apt = self._make_apt('2026-05-14', '10:00', 'monthly',
                             recurrence_end='2026-08-14')
        dates = [r[0] for r in generate_occurrences(apt)]
        self.assertEqual(dates, ['2026-05-14', '2026-06-14', '2026-07-14', '2026-08-14'])

    def test_monthly_clamps_end_of_month(self):
        apt = self._make_apt('2026-01-31', '10:00', 'monthly',
                             recurrence_end='2026-03-31')
        dates = [r[0] for r in generate_occurrences(apt)]
        self.assertIn('2026-02-28', dates)

    # --- Yearly ---

    def test_yearly_increments_year(self):
        apt = self._make_apt('2026-05-14', '10:00', 'yearly',
                             recurrence_end='2028-05-14')
        dates = [r[0] for r in generate_occurrences(apt)]
        self.assertEqual(dates, ['2026-05-14', '2027-05-14', '2028-05-14'])

    # --- Window filtering ---

    def test_from_dt_filters_past(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-06-04')
        from_dt = datetime(2026, 5, 22)  # after first two occurrences
        result = list(generate_occurrences(apt, from_dt=from_dt))
        for date_str, _ in result:
            self.assertGreaterEqual(
                datetime.strptime(date_str, '%Y-%m-%d'), from_dt
            )

    def test_to_dt_filters_future(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-07-14')
        to_dt = datetime(2026, 5, 28)
        result = list(generate_occurrences(apt, to_dt=to_dt))
        for date_str, _ in result:
            self.assertLessEqual(
                datetime.strptime(date_str, '%Y-%m-%d'), to_dt
            )

    def test_window_both_bounds(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-07-14')
        from_dt = datetime(2026, 5, 20)
        to_dt = datetime(2026, 6, 3)
        result = list(generate_occurrences(apt, from_dt=from_dt, to_dt=to_dt))
        self.assertEqual(len(result), 2)  # 21 May, 28 May
        self.assertEqual(result[0][0], '2026-05-21')
        self.assertEqual(result[1][0], '2026-05-28')

    def test_window_empty(self):
        apt = self._make_apt('2026-05-14', '15:00', 'weekly',
                             recurrence_end='2026-06-04')
        # Window entirely before start
        result = list(generate_occurrences(apt, to_dt=datetime(2026, 5, 1)))
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
            ('diário', 'daily'),
            ('todos os dias', 'daily'),
            ('diariamente', 'daily'),
        ]:
            self.assertEqual(FREQ_ALIASES.get(alias), expected, f"Alias '{alias}' failed")

    def test_all_freq_labels_present(self):
        for key in ('daily', 'weekly', 'biweekly', 'monthly', 'yearly'):
            self.assertIn(key, FREQ_LABELS)

    def test_unknown_alias_returns_none(self):
        self.assertIsNone(FREQ_ALIASES.get('horariamente'))
        self.assertIsNone(FREQ_ALIASES.get(''))


# ---------------------------------------------------------------------------
# parse_flexible_date
# ---------------------------------------------------------------------------

class TestParseFlexibleDate(unittest.TestCase):

    def _today(self):
        return datetime.now().date()

    def test_yyyy_mm_dd(self):
        future = (self._today() + timedelta(days=30)).strftime('%Y-%m-%d')
        self.assertEqual(parse_flexible_date(future), future)

    def test_dd_slash_mm(self):
        future = self._today() + timedelta(days=10)
        result = parse_flexible_date(future.strftime('%d/%m'))
        self.assertEqual(result, future.strftime('%Y-%m-%d'))

    def test_dd_slash_mm_yyyy(self):
        future = self._today() + timedelta(days=15)
        result = parse_flexible_date(future.strftime('%d/%m/%Y'))
        self.assertEqual(result, future.strftime('%Y-%m-%d'))

    def test_mm_dash_dd(self):
        future = self._today() + timedelta(days=5)
        result = parse_flexible_date(future.strftime('%m-%d'))
        self.assertEqual(result, future.strftime('%Y-%m-%d'))

    def test_today_is_allowed(self):
        today_str = self._today().strftime('%Y-%m-%d')
        self.assertEqual(parse_flexible_date(today_str), today_str)

    def test_past_date_raises(self):
        yesterday = (self._today() - timedelta(days=1)).strftime('%Y-%m-%d')
        with self.assertRaises(ValueError):
            parse_flexible_date(yesterday)

    def test_too_far_future_raises(self):
        far_future = (self._today() + timedelta(days=731)).strftime('%Y-%m-%d')
        with self.assertRaises(ValueError):
            parse_flexible_date(far_future)

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            parse_flexible_date('not-a-date')

    def test_returns_yyyy_mm_dd_format(self):
        future = self._today() + timedelta(days=20)
        result = parse_flexible_date(future.strftime('%d/%m/%Y'))
        datetime.strptime(result, '%Y-%m-%d')  # must not raise


# ---------------------------------------------------------------------------
# load_appointments / save_appointments
# ---------------------------------------------------------------------------

class TestAppointmentStorage(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp.close()
        self._orig_file = bot_module.APPOINTMENTS_FILE
        bot_module.APPOINTMENTS_FILE = self.tmp.name

    def tearDown(self):
        bot_module.APPOINTMENTS_FILE = self._orig_file
        os.unlink(self.tmp.name)

    def test_load_returns_empty_when_file_missing(self):
        os.unlink(self.tmp.name)
        result = load_appointments()
        self.assertEqual(result, {'appointments': []})
        # Recreate so tearDown doesn't fail
        open(self.tmp.name, 'w').close()

    def test_save_and_load_roundtrip(self):
        data = {'appointments': [{'id': 1, 'date': '2026-06-01', 'time': '10:00'}]}
        save_appointments(data)
        loaded = load_appointments()
        self.assertEqual(loaded, data)

    def test_save_preserves_unicode(self):
        data = {'appointments': [{'description': 'Médico João'}]}
        save_appointments(data)
        loaded = load_appointments()
        self.assertEqual(loaded['appointments'][0]['description'], 'Médico João')

    def test_load_empty_json_file(self):
        with open(self.tmp.name, 'w') as f:
            json.dump({'appointments': []}, f)
        result = load_appointments()
        self.assertEqual(result['appointments'], [])


# ---------------------------------------------------------------------------
# was_reminder_sent / save_sent_reminder_occurrence
# ---------------------------------------------------------------------------

class TestSentReminders(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp.close()
        self._orig_file = bot_module.SENT_REMINDERS_FILE
        bot_module.SENT_REMINDERS_FILE = self.tmp.name
        # Start with empty reminders file
        with open(self.tmp.name, 'w') as f:
            json.dump({'reminders': []}, f)

    def tearDown(self):
        bot_module.SENT_REMINDERS_FILE = self._orig_file
        os.unlink(self.tmp.name)

    def test_not_sent_initially(self):
        self.assertFalse(was_reminder_sent(1, '2026-05-14', '24h'))

    def test_sent_after_save(self):
        save_sent_reminder_occurrence(1, '2026-05-14', '24h')
        self.assertTrue(was_reminder_sent(1, '2026-05-14', '24h'))

    def test_different_occurrence_date_not_marked(self):
        save_sent_reminder_occurrence(1, '2026-05-14', '24h')
        self.assertFalse(was_reminder_sent(1, '2026-05-21', '24h'))

    def test_different_reminder_type_not_marked(self):
        save_sent_reminder_occurrence(1, '2026-05-14', '24h')
        self.assertFalse(was_reminder_sent(1, '2026-05-14', '2h'))

    def test_different_appointment_id_not_marked(self):
        save_sent_reminder_occurrence(1, '2026-05-14', '24h')
        self.assertFalse(was_reminder_sent(2, '2026-05-14', '24h'))

    def test_duplicate_save_does_not_duplicate_key(self):
        save_sent_reminder_occurrence(1, '2026-05-14', '24h')
        save_sent_reminder_occurrence(1, '2026-05-14', '24h')
        with open(self.tmp.name) as f:
            data = json.load(f)
        keys = [k for k in data['reminders'] if k == '1_2026-05-14_24h']
        self.assertEqual(len(keys), 1)

    def test_multiple_occurrences_tracked_independently(self):
        save_sent_reminder_occurrence(5, '2026-05-14', '24h')
        save_sent_reminder_occurrence(5, '2026-05-21', '24h')
        self.assertTrue(was_reminder_sent(5, '2026-05-14', '24h'))
        self.assertTrue(was_reminder_sent(5, '2026-05-21', '24h'))
        self.assertFalse(was_reminder_sent(5, '2026-05-28', '24h'))


# ---------------------------------------------------------------------------
# is_user_allowed (whitelist)
# ---------------------------------------------------------------------------

class TestIsUserAllowed(unittest.TestCase):

    def setUp(self):
        self._orig = bot_module.ALLOWED_USER_IDS[:]

    def tearDown(self):
        bot_module.ALLOWED_USER_IDS[:] = self._orig

    def test_empty_whitelist_allows_everyone(self):
        bot_module.ALLOWED_USER_IDS.clear()
        self.assertTrue(is_user_allowed(99999))

    def test_whitelisted_user_allowed(self):
        bot_module.ALLOWED_USER_IDS[:] = [123, 456]
        self.assertTrue(is_user_allowed(123))
        self.assertTrue(is_user_allowed(456))

    def test_non_whitelisted_user_denied(self):
        bot_module.ALLOWED_USER_IDS[:] = [123]
        self.assertFalse(is_user_allowed(999))

    def test_user_not_in_empty_list_denied_after_population(self):
        bot_module.ALLOWED_USER_IDS[:] = [1]
        self.assertFalse(is_user_allowed(2))

if __name__ == '__main__':
    unittest.main(verbosity=2)
