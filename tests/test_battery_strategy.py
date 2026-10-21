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
