"""Hourly battery-threshold simulator for an SBU hybrid inverter (no grid charging).

Models the inverter rule "battery until SOC <= low, then grid until SOC >= high"
(the 20/30 and 40/50 settings). Pure Python so it runs inside the slim container
and against either modelled PV (weather archive) or measured inverter history.

All energies are kWh per step; one step = one hour unless `step_hours` changes.
"""
from dataclasses import dataclass, field
from math import cos, pi

# Typical Chilean residential profile (fraction of daily kWh per local hour).
# An ASSUMPTION used only when no measured load exists; replaced by real data.
LOAD_SHAPE = (0.025, 0.022, 0.020, 0.020, 0.020, 0.022, 0.030, 0.042, 0.045, 0.040, 0.038, 0.038,
              0.042, 0.042, 0.038, 0.036, 0.038, 0.045, 0.055, 0.065, 0.068, 0.062, 0.050, 0.035)
_SHAPE_SUM = sum(LOAD_SHAPE)

SUMMER_MONTHS = (10, 11, 12, 1, 2, 3)


@dataclass
class System:
    capacity_kwh: float = 11.0          # measured ~11 kWh per 100 % SOC (Oct 2026 data)
    pv_kwp: float = 9.92                # 16 x 620 W
    ac_limit_kw: float = 8.0            # real sunny-day ceiling given by the owner
    performance_ratio: float = 0.80     # wiring, soiling, mismatch, MPPT, inverter
    temp_coeff: float = -0.0035         # Pmax %/°C typical for mono PERC/TOPCon
    charge_eff: float = 0.90            # measured round trip ~0.77-0.80 incl. BMS SOC error
    discharge_eff: float = 0.88
    idle_kw: float = 0.05               # inverter self-consumption, measured ~50 W
    max_charge_kw: float = 6.0
    max_discharge_kw: float = 8.0
    # Measured: in line mode (L) the house runs from the grid and PV only charges the battery.
    pv_feeds_load_on_grid: bool = False


@dataclass
class Strategy:
    name: str
    low: dict = field(default_factory=dict)    # month -> back-to-grid SOC %
    high: dict = field(default_factory=dict)   # month -> back-to-battery SOC %

    @classmethod
    def fixed(cls, low, high):
        return cls(f'{low}/{high}', {m: low for m in range(1, 13)}, {m: high for m in range(1, 13)})

    @classmethod
    def seasonal(cls, summer, winter, summer_months=SUMMER_MONTHS):
        low = {m: (summer if m in summer_months else winter)[0] for m in range(1, 13)}
        high = {m: (summer if m in summer_months else winter)[1] for m in range(1, 13)}
        return cls(f'{summer[0]}/{summer[1]} verano · {winter[0]}/{winter[1]} invierno', low, high)

    @classmethod
    def monthly(cls, name, lows, gap=10):
        return cls(name, dict(lows), {m: min(100, v + gap) for m, v in lows.items()})


def pv_from_irradiance(gti, temp_c, system):
    """AC kW from plane-of-array irradiance (W/m²) and air temperature."""
    if gti is None or gti <= 0:
        return 0.0
    cell = (temp_c if temp_c is not None else 12.0) + gti / 800 * 25
    dc = gti / 1000 * system.pv_kwp * system.performance_ratio * (1 + system.temp_coeff * (cell - 25))
    return max(0.0, min(system.ac_limit_kw, dc))


def seasonal_load_factor(month, winter_extra=0.25):
    """1.0 in January rising to 1+winter_extra in July (southern hemisphere)."""
    return 1 + winter_extra * (1 - cos(2 * pi * (month - 1) / 12)) / 2


def modelled_load(hour, month, daily_kwh, winter_extra=0.25):
    return daily_kwh * LOAD_SHAPE[hour] / _SHAPE_SUM * seasonal_load_factor(month, winter_extra)


def simulate(steps, system, strategy, start_soc=60.0, step_hours=1.0):
    """steps: iterable of (month, pv_kwh, load_kwh). Returns totals and per-month detail."""
    cap = system.capacity_kwh
    soc = cap * start_soc / 100
    on_grid = False
    t = dict(pv=0.0, load=0.0, grid=0.0, curtailed=0.0, charged=0.0, discharged=0.0,
             transfers=0, hours=0, hours_below_30=0, hours_on_grid=0, soc_sum=0.0)
    months = {}
    for month, pv, load in steps:
        load += system.idle_kw * step_hours
        low, high = cap * strategy.low[month] / 100, cap * strategy.high[month] / 100
        m = months.setdefault(month, dict(pv=0.0, load=0.0, grid=0.0, curtailed=0.0, discharged=0.0, n=0))
        charge_room = max(0.0, (cap - soc) / system.charge_eff)
        charge_limit = system.max_charge_kw * step_hours
        grid = curtailed = charged = discharged = 0.0
        if on_grid:
            direct = min(pv, load) if system.pv_feeds_load_on_grid else 0.0
            surplus = pv - direct
            charged = min(surplus, charge_room, charge_limit)
            curtailed = surplus - charged
            grid = load - direct
        else:
            if pv >= load:
                charged = min(pv - load, charge_room, charge_limit)
                curtailed = pv - load - charged
            else:
                need = load - pv
                available = max(0.0, (soc - low) * system.discharge_eff)
                discharged = min(need, available, system.max_discharge_kw * step_hours)
                grid = need - discharged
        soc += charged * system.charge_eff - discharged / system.discharge_eff
        soc = max(0.0, min(cap, soc))
        if not on_grid and soc <= low + 1e-9 and grid > 0:
            on_grid, t['transfers'] = True, t['transfers'] + 1
        elif on_grid and soc >= high - 1e-9:
            on_grid, t['transfers'] = False, t['transfers'] + 1
        pct = soc / cap * 100
        for key, value in (('pv', pv), ('load', load), ('grid', grid), ('curtailed', curtailed),
                           ('charged', charged), ('discharged', discharged)):
            t[key] += value
        for key, value in (('pv', pv), ('load', load), ('grid', grid), ('curtailed', curtailed), ('discharged', discharged)):
            m[key] += value
        m['n'] += 1
        t['hours'] += 1
        t['hours_below_30'] += pct < 30
        t['hours_on_grid'] += on_grid
        t['soc_sum'] += pct
    t['cycles'] = t['discharged'] / cap if cap else 0
    t['mean_soc'] = t['soc_sum'] / t['hours'] if t['hours'] else 0
    t['self_sufficiency'] = 1 - t['grid'] / t['load'] if t['load'] else 0
    return t, months


def cost(result, years, tariff_clp_kwh=230.0, wear_clp_kwh=45.0):
    """Annual grid cost plus battery wear (CLP). Wear = bank price / lifetime kWh throughput."""
    return (result['grid'] * tariff_clp_kwh + result['discharged'] * wear_clp_kwh) / years
