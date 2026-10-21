import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import control
from cloud import Cloud, PARAM_SET

PARAMS = {'BCRC': '20 5~60', 'BCRD': '50 10~100', 'PC': '3 1,2,3', 'BT': '4 0,1,2,3,4'}
WINTER_NIGHT = datetime(2026, 6, 15, 23, 30, tzinfo=timezone.utc)   # 19:30 local
SPRING_NOON = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)


def cfg(**over):
    with patch.dict(os.environ, {}, clear=False):
        base = control.config()
    base.update(mode='on', **over)
    return base


class ParseTests(unittest.TestCase):
    def test_ranges_options_and_soc_mode(self):
        self.assertEqual(control.parse_param('20 5~60'), {'value': 20, 'min': 5.0, 'max': 60.0})
        self.assertEqual(control.parse_param('3 1,2,3'), {'value': 3, 'options': [1, 2, 3]})
        current = control.current_settings(PARAMS)
        self.assertTrue(current['soc_mode'])
        self.assertFalse(control.current_settings({**PARAMS, 'BT': '1 0,1,2'})['soc_mode'])


class PolicyTests(unittest.TestCase):
    def test_base_winter_storm_and_calibration(self):
        c = cfg()
        base = control.desired(c, SPRING_NOON, {}, [], None, False)
        self.assertEqual((base['to_grid'], base['to_battery'], base['charger']), (20, 30, 3))
        winter = control.desired(c, WINTER_NIGHT, {}, [], None, False)
        self.assertEqual((winter['to_grid'], winter['to_battery']), (40, 50))
        rainy = control.desired(c, SPRING_NOON, {}, [{'date': '2026-10-21', 'gust_max_kmh': 45, 'precipitation_mm': 100}], None, False)
        self.assertEqual(rainy['to_grid'], 20)  # ordinary Valdivia rain is not a storm
        storm = control.desired(c, SPRING_NOON, {}, [{'date': '2026-10-22', 'gust_max_kmh': 85, 'precipitation_mm': 3}], None, False)
        self.assertEqual((storm['to_grid'], storm['to_battery']), (40, 50))
        self.assertIn('temporal', storm['reason'])
        cal = control.desired(c, WINTER_NIGHT, {'days_since_full_charge': 12}, [], None, False)
        self.assertEqual((cal['to_battery'], cal['charger'], cal['calibrating']), (100, 2, True))
        done = control.desired(c, WINTER_NIGHT, {'days_since_full_charge': 0}, [], WINTER_NIGHT - timedelta(hours=8), True)
        self.assertFalse(done['calibrating'])

    def test_manual_hold_wins_until_it_expires(self):
        hold = {'to_grid': 40, 'to_battery': 50, 'charger': 3, 'hold_until': (SPRING_NOON + timedelta(hours=2)).isoformat()}
        self.assertEqual(control.desired(cfg(), SPRING_NOON, {}, [], None, False, hold)['to_grid'], 40)
        self.assertEqual(control.desired(cfg(), SPRING_NOON + timedelta(hours=3), {}, [], None, False, hold)['to_grid'], 20)

    def test_validation_refuses_unsafe_or_out_of_range_values(self):
        current = control.current_settings(PARAMS)
        ok = {'to_grid': 20, 'to_battery': 30, 'charger': 3}
        self.assertEqual(control.validate(ok, current, cfg()), [])
        for bad in ({'to_grid': 10, 'to_battery': 30, 'charger': 3}, {'to_grid': 20, 'to_battery': 20, 'charger': 3},
                    {'to_grid': 22, 'to_battery': 30, 'charger': 3}, {'to_grid': 20, 'to_battery': 30, 'charger': 0},
                    {'to_grid': 65, 'to_battery': 100, 'charger': 3}):
            self.assertTrue(control.validate(bad, current, cfg()), bad)

    def test_plan_only_sends_differences(self):
        current = control.current_settings(PARAMS)
        self.assertEqual(control.plan({'to_grid': 20, 'to_battery': 30, 'charger': 3}, current), ['PBDC030'])
        self.assertEqual(control.plan({'to_grid': 40, 'to_battery': 50, 'charger': 2}, current), ['PBCC040', 'PCP02'])


class CloudWriteTests(unittest.TestCase):
    def test_only_whitelisted_commands_reach_the_vendor(self):
        session = Mock()
        client = Cloud('u', 'p', session)
        for bad in (['POP02'], ['PBCC020\n'], ['PCP00'], [], ['PBCC020'] * 4, ['PDa']):
            with self.assertRaises(ValueError):
                client.send_settings('SN', bad)
        session.post.assert_not_called()

    def test_payload_matches_portal_format(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200, json=Mock(return_value={'code': 0}))
        client = Cloud('u', 'p', session)
        client.token = 'T'
        self.assertEqual(client.send_settings('SN', ['PBCC020', 'PBDC030']), ('0', ''))
        call = session.post.call_args
        self.assertTrue(call.args[0].endswith(PARAM_SET))
        self.assertEqual(json.loads(call.kwargs['data']['commands']), {'S01': 'PBCC020', 'S02': 'PBDC030'})


if __name__ == '__main__':
    unittest.main()


class DeviceStatusTests(unittest.TestCase):
    def test_online_status_is_read_from_device_list(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200, json=Mock(return_value={'code': 0, 'data': {'list': [
            {'deviceSn': 'OTHER', 'onlineStatus': 1}, {'deviceSn': 'SN', 'onlineStatus': 0, 'modifyTime': '2026-10-21 11:00:00'}]}}))
        client = Cloud('u', 'p', session)
        client.token = 'T'
        self.assertEqual(client.device_status('SN'), {'online': False, 'updated': '2026-10-21 11:00:00'})
        self.assertEqual(client.device_status('MISSING')['online'], None)
