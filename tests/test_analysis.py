import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import analysis

T0 = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)  # 12:00 Chile (UTC-3)


def sample(minutes, **payload):
    base = {'workMode': 'B', 'batteryCapacity': 50, 'batteryVoltage': 52.5, 'pvInputPower1': 0,
            'pvInputPower2': 0, 'acOutputActivePowerTotal': 0, 'gridPowerInputActiveTotal': 0,
            'batteryChargingPower': 0, 'batteryDischargingPower': 0}
    base.update(payload)
    return T0 + timedelta(minutes=minutes), analysis.derive(base)


class DeriveTests(unittest.TestCase):
    def test_grid_field_is_import_only_in_line_mode(self):
        battery_mode = analysis.derive({'workMode': 'B', 'gridPowerInputActiveTotal': 1333, 'acOutputActivePowerTotal': 1376})
        line_mode = analysis.derive({'workMode': 'L', 'gridPowerInputActiveTotal': 3510})
        self.assertEqual(battery_mode['grid_import_w'], 0)
        self.assertEqual(line_mode['grid_import_w'], 3510)
        self.assertIsNone(analysis.derive({'gridPowerInputActiveTotal': 5})['grid_import_w'])

    def test_disconnected_bms_is_not_a_zero_percent_battery(self):
        d = analysis.derive({'workMode': 'L', 'batteryCapacity': 0, 'batteryVoltage': 31.4})
        self.assertIsNone(d['soc'])
        self.assertTrue(d['battery_disconnected'])
        self.assertFalse(analysis.derive({'batteryCapacity': 19, 'batteryVoltage': 51})['battery_disconnected'])

    def test_pv_total_keeps_missing_distinct_from_zero(self):
        self.assertIsNone(analysis.derive({})['pv_w'])
        self.assertEqual(analysis.derive({'pvInputPower2': '1360'})['pv_w'], 1360)


class EnergyTests(unittest.TestCase):
    def test_trapezoid_integration_skips_outages(self):
        series = [sample(0, pvInputPower2=1200), sample(5, pvInputPower2=1200), sample(10, pvInputPower2=1200),
                  sample(70, pvInputPower2=1200), sample(75, pvInputPower2=1200)]
        day = analysis.daily_energy(series)[0]
        self.assertAlmostEqual(day['pv_kwh'], 1.2 * 15 / 60, places=3)
        self.assertEqual(day['covered_hours'], 0.25)

    def test_grid_energy_counts_line_mode_only(self):
        series = [sample(0, workMode='B', gridPowerInputActiveTotal=1000, acOutputActivePowerTotal=1000),
                  sample(60, workMode='B', gridPowerInputActiveTotal=1000, acOutputActivePowerTotal=1000)]
        with unittest.mock.patch.object(analysis, 'MAX_GAP', 7200):
            self.assertEqual(analysis.daily_energy(series)[0]['grid_kwh'], 0)

    def test_thresholds_inferred_from_mode_switches(self):
        series = [sample(0, batteryCapacity=22), sample(5, workMode='L', batteryCapacity=19),
                  sample(200, workMode='L', batteryCapacity=49), sample(205, batteryCapacity=50)]
        t = analysis.inferred_thresholds(series)
        self.assertEqual((t['to_grid_soc'], t['to_battery_soc'], t['switches']), (22, 50, 2))

    def test_capacity_from_discharge_windows(self):
        # 1 kW for 3 h at 5-minute samples while SOC falls 30 points -> 10 kWh per 100 %.
        series = [sample(m, batteryDischargingPower=1000, batteryCapacity=80 - m / 6) for m in range(0, 365, 5)]
        self.assertAlmostEqual(analysis.estimate_capacity_kwh(series), 10.0, delta=0.3)


class InsightTests(unittest.TestCase):
    def test_dead_string_and_stale_data_are_reported(self):
        series = [sample(m, pvInputPower2=2000, pvInputVoltage2=310, pvInputVoltage1=0) for m in range(0, 60, 5)]
        codes = {a['code'] for a in analysis.insights(series, now=T0 + timedelta(hours=3))['alerts']}
        self.assertIn('pv1_offline', codes)
        self.assertIn('stale', codes)
        self.assertNotIn('fault', codes)

    def test_textual_empty_warning_list_is_not_a_fault(self):
        series = [sample(0, warning='[]', fault1='0')]
        codes = {a['code'] for a in analysis.insights(series, now=T0)['alerts']}
        self.assertNotIn('fault', codes)


class OutageTests(unittest.TestCase):
    def test_grid_outages_are_detected_with_duration(self):
        volts = [228, 227, 0, 0, 0, 226, 228, 0, 229]
        series = [sample(5 * i, gridVoltageR=v) for i, v in enumerate(volts)]
        outages = analysis.grid_outages(series)
        self.assertEqual([o['minutes'] for o in outages], [15, 5])
        codes = {a['code'] for a in analysis.insights(series, now=T0 + timedelta(minutes=40))['alerts']}
        self.assertIn('grid_outage', codes)


class FieldSeriesTests(unittest.TestCase):
    def test_long_ranges_are_bucketed_not_truncated(self):
        rows = [{'observed_at': T0 + timedelta(minutes=5 * i), 'value': str(i % 10)} for i in range(5000)]
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = rows
        result = analysis.field_series('innerTemperature', T0, T0 + timedelta(days=30), points=1200, db=db)
        self.assertGreater(result['bucket_seconds'], 0)
        self.assertLessEqual(len(result['points']), 1200)
        last = result['points'][-1]
        self.assertGreaterEqual(datetime.fromisoformat(last[0]), T0 + timedelta(days=17))
        self.assertTrue(all(p[2] <= p[1] <= p[3] for p in result['points']))


if __name__ == '__main__':
    unittest.main()
