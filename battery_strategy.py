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
    capacity_kwh: float = 15.36         # NM51.2-300ES01 LiFePO4: 51.2 V x 300 Ah nameplate
    pv_kwp: float = 9.92                # 16 x 620 W
    ac_limit_kw: float = 8.0            # real sunny-day ceiling given by the owner
    performance_ratio: float = 0.80     # wiring, soiling, mismatch, MPPT, inverter
    temp_coeff: float = -0.0035         # Pmax %/°C typical for mono PERC/TOPCon
    charge_eff: float = 0.95            # MPPT/charger + LiFePO4 coulombic losses
    discharge_eff: float = 0.92         # LiFePO4 + inverter DC->AC conversion
    idle_kw: float = 0.05               # inverter self-consumption, measured ~50 W
    max_charge_kw: float = 7.5          # 150 A recommended x ~51 V
    max_discharge_kw: float = 8.0
    # Measured: in line mode (L) the house runs from the grid and PV only charges the battery.
    pv_feeds_load_on_grid: bool = False


@dataclass
class Strategy:
    name: str
    low: dict = field(default_factory=dict)    # month -> back-to-grid SOC %
    high: dict = field(default_factory=dict)   # month -> back-to-battery SOC %
    grid_charge_kw: float = 0.0   # charger "solar + utility": grid tops up the battery in line mode
    calibrate_days: int = 0       # grid full charge at night after this many days without 100 %
    calibrate_kw: float = 3.0

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


def _dc_kw(gti, temp_c, kwp, system):
    if gti is None or gti <= 0:
        return 0.0
    cell = (temp_c if temp_c is not None else 12.0) + gti / 800 * 25
    return max(0.0, gti / 1000 * kwp * system.performance_ratio * (1 + system.temp_coeff * (cell - 25)))


def pv_from_irradiance(gti, temp_c, system):
    """AC kW from plane-of-array irradiance (W/m²) and air temperature."""
    return min(system.ac_limit_kw, _dc_kw(gti, temp_c, system.pv_kwp, system))


def pv_from_planes(planes, temp_c, system):
    """AC kW for strings on different planes [(W/m², kWp), ...] sharing one AC ceiling."""
    return min(system.ac_limit_kw, sum(_dc_kw(gti, temp_c, kwp, system) for gti, kwp in planes))


def seasonal_load_factor(month, winter_extra=0.25):
    """1.0 in January rising to 1+winter_extra in July (southern hemisphere)."""
    return 1 + winter_extra * (1 - cos(2 * pi * (month - 1) / 12)) / 2


def modelled_load(hour, month, daily_kwh, winter_extra=0.25):
    return daily_kwh * LOAD_SHAPE[hour] / _SHAPE_SUM * seasonal_load_factor(month, winter_extra)


def simulate(steps, system, strategy, start_soc=60.0, step_hours=1.0, trace=None):
    """steps: iterable of (month, pv_kwh, load_kwh). Returns totals and per-month detail.

    `trace`, if a list, receives the SOC % after every step."""
    cap = system.capacity_kwh
    soc = cap * start_soc / 100
    on_grid = False
    t = dict(pv=0.0, load=0.0, grid=0.0, curtailed=0.0, charged=0.0, discharged=0.0, grid_charged=0.0,
             transfers=0, hours=0, hours_below_30=0, hours_on_grid=0, hours_above_95=0, soc_sum=0.0,
             calendar_stress=0.0, calibrations=0)
    months = {}
    hours_since_full, calibrating = 0, False
    for month, pv, load in steps:
        if (strategy.calibrate_days and not calibrating and pv <= 0
                and hours_since_full >= strategy.calibrate_days * 24):
            calibrating, t['calibrations'] = True, t['calibrations'] + 1
            if not on_grid:
                on_grid, t['transfers'] = True, t['transfers'] + 1
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
            rate = strategy.calibrate_kw if calibrating else strategy.grid_charge_kw
            if rate > 0:
                from_grid = max(0.0, min(charge_room - charged, rate * step_hours, charge_limit - charged))
                charged += from_grid
                grid += from_grid
                t['grid_charged'] += from_grid
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
        pct = soc / cap * 100
        hours_since_full = 0 if pct >= 98 else hours_since_full + 1
        if calibrating and pct >= 99:
            calibrating = False
        if not on_grid and soc <= low + 1e-9 and grid > 0:
            on_grid, t['transfers'] = True, t['transfers'] + 1
        elif on_grid and not calibrating and soc >= high - 1e-9:
            on_grid, t['transfers'] = False, t['transfers'] + 1
        if trace is not None:
            trace.append(pct)
        for key, value in (('pv', pv), ('load', load), ('grid', grid), ('curtailed', curtailed),
                           ('charged', charged), ('discharged', discharged)):
            t[key] += value
        for key, value in (('pv', pv), ('load', load), ('grid', grid), ('curtailed', curtailed), ('discharged', discharged)):
            m[key] += value
        m['n'] += 1
        t['hours'] += 1
        t['hours_below_30'] += pct < 30
        t['hours_on_grid'] += on_grid
        t['hours_above_95'] += pct > 95
        t['soc_sum'] += pct
        t['calendar_stress'] += 0.6 + 0.8 * pct / 100  # 1.0 at 50 % SOC, 1.4 at 100 %
    t['cycles'] = t['discharged'] / cap if cap else 0
    t['mean_soc'] = t['soc_sum'] / t['hours'] if t['hours'] else 0
    t['self_sufficiency'] = 1 - t['grid'] / t['load'] if t['load'] else 0
    return t, months


def battery_life(result, years, temp_c=20.0, calendar_pct_year=1.5, cycles_to_80=6000):
    """Rough LiFePO4 ageing: calendar fade (SOC- and temperature-dependent) plus cycle fade.

    calendar_pct_year: capacity loss per year at 25 °C and 50 % SOC (literature/field
    range ~1-2 %/year); doubled per +10 °C. Cycle fade: 20 % after `cycles_to_80`
    equivalent full cycles (typical 6000 @ 80 % DoD datasheets). Linear in time,
    which is conservative: real calendar fade slows down with age.
    """
    hours = result['hours'] or 1
    calendar = calendar_pct_year * 2 ** ((temp_c - 25) / 10) * result['calendar_stress'] / hours
    cycling = result['cycles'] / years * 20 / cycles_to_80
    fade = calendar + cycling
    return {'fade_pct_year': round(fade, 2), 'calendar_pct_year': round(calendar, 2), 'cycle_pct_year': round(cycling, 2),
            'years_to_80': round(20 / fade, 1), 'years_to_70': round(30 / fade, 1)}


def cost(result, years, tariff_clp_kwh=230.0, wear_clp_kwh=45.0):
    """Annual grid cost plus battery wear (CLP). Wear = bank price / lifetime kWh throughput."""
    return (result['grid'] * tariff_clp_kwh + result['discharged'] * wear_clp_kwh) / years
