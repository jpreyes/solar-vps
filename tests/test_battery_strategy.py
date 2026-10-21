import unittest
from battery_strategy import Strategy, System, pv_from_irradiance, simulate


def days(n, pv_day, load_hour=0.6):
    steps = []
    for _ in range(n):
        for hour in range(24):
            pv = pv_day / 8 if 9 <= hour < 17 else 0.0
            steps.append((7, pv, load_hour))
    return steps


class StrategyTests(unittest.TestCase):
    def test_pv_model_respects_inverter_ceiling(self):
        system = System()
        self.assertEqual(pv_from_irradiance(1300, 5, system), system.ac_limit_kw)
        self.assertEqual(pv_from_irradiance(0, 20, system), 0)
        self.assertLess(pv_from_irradiance(1000, 35, system), pv_from_irradiance(1000, 0, system))

    def test_lower_floor_never_uses_more_grid_when_surplus_exists(self):
        steps = days(30, pv_day=20)
        low, _ = simulate(steps, System(capacity_kwh=10), Strategy.fixed(20, 30))
        high, _ = simulate(steps, System(capacity_kwh=10), Strategy.fixed(40, 50))
        self.assertLessEqual(low['grid'], high['grid'])

    def test_line_mode_runs_loads_from_grid_until_return_threshold(self):
        steps = days(10, pv_day=8)
        wide, _ = simulate(steps, System(capacity_kwh=10, pv_feeds_load_on_grid=False), Strategy.fixed(20, 60))
        narrow, _ = simulate(steps, System(capacity_kwh=10, pv_feeds_load_on_grid=False), Strategy.fixed(20, 30))
        self.assertGreater(wide['grid'], narrow['grid'])

    def test_energy_balance_closes(self):
        system = System(capacity_kwh=10, idle_kw=0)
        r, _ = simulate(days(20, pv_day=12), system, Strategy.fixed(20, 30), start_soc=60)
        stored = r['charged'] * system.charge_eff - r['discharged'] / system.discharge_eff
        self.assertAlmostEqual(r['pv'] - r['curtailed'] - r['charged'] + r['discharged'] + r['grid'], r['load'], places=6)
        self.assertGreaterEqual(10 * 0.6 + stored, -1e-9)

    def test_seasonal_strategy_uses_winter_thresholds_in_july(self):
        s = Strategy.seasonal((20, 30), (40, 50))
        self.assertEqual((s.low[7], s.high[7], s.low[1], s.high[1]), (40, 50, 20, 30))


if __name__ == '__main__':
    unittest.main()


class PlaneTests(unittest.TestCase):
    def test_two_planes_share_one_ac_ceiling(self):
        from battery_strategy import pv_from_planes
        system = System(ac_limit_kw=8)
        self.assertEqual(pv_from_planes([(1100, 4.96), (1100, 4.96)], 5, system), 8)
        one = pv_from_planes([(600, 4.96), (0, 4.96)], 15, system)
        self.assertAlmostEqual(pv_from_planes([(600, 4.96), (600, 4.96)], 15, system), 2 * one)


class FullChargeTests(unittest.TestCase):
    def test_winter_full_days_and_streaks(self):
        from datetime import date, timedelta
        from analysis import full_charge_stats
        days = [date(2025, 6, 1) + timedelta(days=i) for i in range(30)]
        trace = [100 if i % 10 == 0 else 60 for i in range(30)]
        stats = full_charge_stats(days, trace)
        self.assertAlmostEqual(stats['winter_full_days'], 0.1)
        self.assertEqual(stats['streak_worst_days'], 9)


class GridChargeAndLifeTests(unittest.TestCase):
    def test_grid_charging_with_flat_tariff_only_adds_grid_energy(self):
        steps = days(30, pv_day=12)
        plain, _ = simulate(steps, System(capacity_kwh=15), Strategy.fixed(20, 30))
        grid = Strategy.fixed(20, 30)
        grid.grid_charge_kw = 3
        charged, _ = simulate(steps, System(capacity_kwh=15), grid)
        self.assertGreater(charged['grid_charged'], 0)
        self.assertGreater(charged['grid'], plain['grid'])

    def test_calibration_charge_reaches_full_after_dry_spell(self):
        cal = Strategy.fixed(20, 30)
        cal.calibrate_days = 5
        trace = []
        result, _ = simulate(days(20, pv_day=2), System(capacity_kwh=15), cal, trace=trace)
        self.assertGreaterEqual(result['calibrations'], 2)
        self.assertGreaterEqual(max(trace), 99)

    def test_life_is_calendar_dominated_at_low_cycle_counts(self):
        from battery_strategy import battery_life
        r, _ = simulate(days(365, pv_day=20), System(capacity_kwh=15), Strategy.fixed(20, 30))
        life = battery_life(r, 1.0)
        self.assertGreater(life['calendar_pct_year'], life['cycle_pct_year'])
        self.assertGreater(life['years_to_70'], life['years_to_80'])
