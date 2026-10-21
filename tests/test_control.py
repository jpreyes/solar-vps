import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import control
from cloud import Cloud, PARAM_SET

PARAMS = {'BCRC': '20 5~60', 'BCRD': '50 10~100', 'PC': '3 1,2,3', 'BT': '4 0,1,2,3,4', 'MCC': '190 10~200', 'MCG': '2 2,10~180'}
WINTER_NIGHT = datetime(2026, 6, 15, 23, 30, tzinfo=timezone.utc)   # 19:30 local
SPRING_NOON = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)


def cfg(**over):
    with patch.dict(os.environ, {}, clear=False):
        base = control.config()
    base.update(mode='on', calibration=True)
    base.update(**over)
    return base


class ParseTests(unittest.TestCase):
    def test_ranges_options_and_soc_mode(self):
        self.assertEqual(control.parse_param('20 5~60'), {'value': 20, 'ranges': [(5.0, 60.0)], 'min': 5.0, 'max': 60.0})
        mcg = control.parse_param('2 2,10~180')
        self.assertEqual((mcg['value'], mcg['options'], mcg['ranges']), (2, [2], [(10.0, 180.0)]))
        self.assertTrue(control.allowed(2, mcg) and control.allowed(30, mcg))
        self.assertFalse(control.allowed(5, mcg))
        self.assertEqual(control.parse_param('3 1,2,3'), {'value': 3, 'options': [1, 2, 3], 'min': 1, 'max': 3})
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
        self.assertEqual(control.plan({'to_grid': 20, 'to_battery': 30, 'charger': 3, 'charge_a': 190, 'grid_charge_a': 2}, current), ['PBDC030'])

    def test_grid_charging_lowers_currents_first_and_restores_them_last(self):
        current = control.current_settings(PARAMS)
        enter = control.plan({'to_grid': 20, 'to_battery': 100, 'charger': 2, 'charge_a': 30, 'grid_charge_a': 30}, current)
        self.assertEqual(enter, ['MNCHGC030', 'MUCHGC030', 'PCP02', 'PBDC100'])
        during = control.current_settings({**PARAMS, 'MCC': '30 10~200', 'MCG': '30 2,10~180', 'PC': '2 1,2,3', 'BCRD': '100 10~100'})
        leave = control.plan({'to_grid': 20, 'to_battery': 30, 'charger': 3, 'charge_a': 190, 'grid_charge_a': 2}, during)
        self.assertEqual(leave, ['PCP03', 'MUCHGC002', 'MNCHGC190', 'PBDC030'])

    def test_grid_charger_is_never_enabled_with_high_currents(self):
        current = control.current_settings(PARAMS)
        unsafe = {'to_grid': 20, 'to_battery': 30, 'charger': 2, 'charge_a': 190, 'grid_charge_a': 2}
        self.assertTrue(any('red' in p for p in control.validate(unsafe, current, cfg())))
        safe = control.safe_currents(dict(unsafe), cfg())
        self.assertEqual((safe['charge_a'], safe['grid_charge_a']), (30, 30))
        self.assertEqual(control.validate(safe, current, cfg()), [])
        solar_first = control.safe_currents({'to_grid': 20, 'to_battery': 30, 'charger': 1, 'charge_a': 150, 'grid_charge_a': 2}, cfg())
        self.assertEqual(solar_first['charge_a'], 30)

    def test_calibration_uses_capped_currents_and_ends_at_dawn(self):
        c = cfg()
        cal = control.desired(c, WINTER_NIGHT, {'days_since_full_charge': 12}, [], None, False, keep={'charge_a': 190})
        self.assertEqual((cal['charger'], cal['charge_a'], cal['grid_charge_a']), (2, 30, 30))
        dawn = datetime(2026, 6, 16, 12, 30, tzinfo=timezone.utc)  # 08:30 local
        after = control.desired(c, dawn, {'days_since_full_charge': 12}, [], WINTER_NIGHT, False, keep={'charge_a': 190})
        self.assertEqual((after['charger'], after['charge_a'], after['grid_charge_a'], after['calibrating']), (3, 190, 2, False))


class CloudWriteTests(unittest.TestCase):
    def test_only_whitelisted_commands_reach_the_vendor(self):
        session = Mock()
        client = Cloud('u', 'p', session)
        for bad in (['POP02'], ['PBCC020\n'], ['PCP00'], [], ['PBCC020'] * 6, ['PDa'], ['MNCHGC30'], ['MGCHGC030']):
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
        status = client.device_status('SN')
        self.assertEqual((status['online'], status['updated']), (False, '2026-10-21 11:00:00'))
        self.assertEqual(client.device_status('MISSING')['online'], None)
