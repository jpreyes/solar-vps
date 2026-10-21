"""Derived energy metrics, alerts and battery-strategy study from the SQL archive.

Field semantics confirmed with the owner's VM II Premium+ 12K data (Oct 2026):
- workMode 'B' = battery/inverter mode, 'L' = line (grid) mode.
- gridPowerInputActiveTotal mirrors the AC output in mode B: it is NOT grid
  import there. Real grid import exists only in mode L (statusGrid=1).
- In mode L the loads run from the grid and PV only charges the battery.
- batteryChargingPower / batteryDischargingPower are DC-side battery power.
"""
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo
from battery_strategy import (System, Strategy, LOAD_SHAPE, battery_life, cost, pv_from_irradiance,
                              pv_from_planes, seasonal_load_factor, simulate)
from storage import connect

MAX_GAP = 900  # seconds; never integrate power across longer outages
FIELDS = ('workMode', 'statusGrid', 'gridVoltageR', 'pvInputPower1', 'pvInputPower2', 'pvInputVoltage1', 'pvInputVoltage2',
          'acOutputActivePowerTotal', 'gridPowerInputActiveTotal', 'batteryChargingPower',
          'batteryDischargingPower', 'batteryCapacity', 'batteryVoltage', 'innerTemperature',
          'maxTemperature', 'fault1', 'warning')


def tz():
    return ZoneInfo(os.getenv('DEVICE_TIMEZONE', 'America/Santiago'))


def num(value):
    if value is None or isinstance(value, bool) or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float('inf') else None


def battery_reading_valid(payload):
    """A disconnected BMS reports SOC 0 and ~31 V: not a real state of charge."""
    soc, volts = num(payload.get('batteryCapacity')), num(payload.get('batteryVoltage'))
    return soc is not None and volts is not None and volts >= 40 and not (soc == 0 and volts < 45)


def grid_mode(payload):
    mode = payload.get('workMode')
    if mode in ('B', 'L'):
        return mode == 'L'
    status = num(payload.get('statusGrid'))
    return None if status is None else status == 1


def derive(payload):
    pv1, pv2 = num(payload.get('pvInputPower1')), num(payload.get('pvInputPower2'))
    on_grid = grid_mode(payload)
    grid_field = num(payload.get('gridPowerInputActiveTotal'))
    valid = battery_reading_valid(payload)
    return {
        'pv_w': None if pv1 is None and pv2 is None else (pv1 or 0) + (pv2 or 0),
        'pv1_w': pv1, 'pv2_w': pv2,
        'pv1_v': num(payload.get('pvInputVoltage1')), 'pv2_v': num(payload.get('pvInputVoltage2')),
        'load_w': num(payload.get('acOutputActivePowerTotal')),
        'grid_import_w': None if on_grid is None else (grid_field or 0) if on_grid else 0.0,
        'on_grid': on_grid,
        'battery_charge_w': num(payload.get('batteryChargingPower')),
        'battery_discharge_w': num(payload.get('batteryDischargingPower')),
        'soc': num(payload.get('batteryCapacity')) if valid else None,
        'battery_v': num(payload.get('batteryVoltage')) if valid else None,
        'battery_valid': valid,
        'battery_disconnected': not valid and num(payload.get('batteryVoltage')) is not None,
        'grid_v': num(payload.get('gridVoltageR')),
        'inner_temp': num(payload.get('innerTemperature')),
        'max_temp': num(payload.get('maxTemperature')),
        'fault': num(payload.get('fault1')),
        'warning': payload.get('warning'),
    }


DERIVED_LABELS = {'pv_w': 'pvTotal', 'grid_import_w': 'gridImport', 'battery_charge_w': 'batteryChargingPower',
                  'battery_discharge_w': 'batteryDischargingPower'}


def samples(start, end, db=None):
    """Deduplicated inverter samples (history preferred over realtime) with derived fields."""
    sql = '''SELECT DISTINCT ON (observed_at) observed_at, {fields}
      FROM measurements WHERE source IN ('history','realtime') AND observed_at >= %s AND observed_at < %s
      ORDER BY observed_at, (source='history') DESC, id DESC'''.format(
        fields=','.join(f"payload->>'{f}' AS \"{f}\"" for f in FIELDS))
    def run(database):
        return database.execute(sql, (start, end)).fetchall()
    rows = run(db) if db is not None else _with_db(run)
    return [(row['observed_at'], derive(row)) for row in rows]


def _with_db(fn):
    with connect() as db:
        return fn(db)


def integrate(series, key, max_gap=MAX_GAP):
    """Trapezoidal kWh of a W series, split per local day, skipping long gaps."""
    days = defaultdict(float)
    zone = tz()
    for (t0, a), (t1, b) in zip(series, series[1:]):
        dt = (t1 - t0).total_seconds()
        if dt <= 0 or dt > max_gap or a[key] is None or b[key] is None:
            continue
        days[t0.astimezone(zone).date()] += (a[key] + b[key]) / 2 * dt / 3_600_000
    return days


def daily_energy(series):
    keys = {'pv_kwh': 'pv_w', 'load_kwh': 'load_w', 'grid_kwh': 'grid_import_w',
            'battery_in_kwh': 'battery_charge_w', 'battery_out_kwh': 'battery_discharge_w'}
    totals = {name: integrate(series, key) for name, key in keys.items()}
    zone = tz()
    info = defaultdict(lambda: {'soc_min': None, 'soc_max': None, 'grid_mode_hours': 0.0, 'covered_hours': 0.0})
    for (t0, a), (t1, _) in zip(series, series[1:]):
        dt = (t1 - t0).total_seconds()
        day = info[t0.astimezone(zone).date()]
        if 0 < dt <= MAX_GAP:
            day['covered_hours'] += dt / 3600
            if a['on_grid']:
                day['grid_mode_hours'] += dt / 3600
        if a['soc'] is not None:
            day['soc_min'] = a['soc'] if day['soc_min'] is None else min(day['soc_min'], a['soc'])
            day['soc_max'] = a['soc'] if day['soc_max'] is None else max(day['soc_max'], a['soc'])
    out = []
    for day in sorted(info):
        row = {'date': day.isoformat(), **{k: round(v[day], 3) for k, v in totals.items()}, **info[day]}
        row['covered_hours'] = round(row['covered_hours'], 2)
        row['grid_mode_hours'] = round(row['grid_mode_hours'], 2)
        row['self_sufficiency'] = (round(min(1, max(0, 1 - row['grid_kwh'] / row['load_kwh'])), 3)
                                   if row['load_kwh'] > 0.5 else None)
        out.append(row)
    return out


def mode_transitions(series):
    """Battery->grid and grid->battery switches with the SOC at the switch."""
    out, previous = [], None
    for t, d in series:
        if d['on_grid'] is None or not d['battery_valid']:
            continue
        if previous and previous[1]['on_grid'] != d['on_grid']:
            before, after = previous[1], d
            out.append({'time': t, 'to': 'grid' if d['on_grid'] else 'battery',
                        'soc': before['soc'] if d['on_grid'] else after['soc']})
        previous = (t, d)
    return out


def inferred_thresholds(series):
    moves = mode_transitions(series)
    to_grid = [m['soc'] for m in moves if m['to'] == 'grid' and m['soc'] is not None]
    to_battery = [m['soc'] for m in moves if m['to'] == 'battery' and m['soc'] is not None]
    return {'to_grid_soc': median(to_grid) if to_grid else None,
            'to_battery_soc': median(to_battery) if to_battery else None,
            'switches': len(moves), 'samples': {'to_grid': to_grid[-10:], 'to_battery': to_battery[-10:]}}


def estimate_capacity_kwh(series, window=timedelta(hours=3)):
    """kWh per 100 % SOC from battery discharge energy over falling-SOC windows."""
    energy = soc_drop = 0.0
    start = None
    for (t0, a), (t1, b) in zip(series, series[1:]):
        if not (a['battery_valid'] and b['battery_valid']):
            start = None
            continue
        if start is None:
            start, start_soc, discharged, charged = t0, a['soc'], 0.0, 0.0
        dt = (t1 - t0).total_seconds()
        if 0 < dt <= MAX_GAP:
            discharged += ((a['battery_discharge_w'] or 0) + (b['battery_discharge_w'] or 0)) / 2 * dt / 3_600_000
            charged += ((a['battery_charge_w'] or 0) + (b['battery_charge_w'] or 0)) / 2 * dt / 3_600_000
        if t1 - start >= window:
            drop = start_soc - b['soc']
            if drop >= 5 and charged < 0.05 * discharged:
                energy, soc_drop = energy + discharged, soc_drop + drop
            start = None
    return round(energy / soc_drop * 100, 1) if soc_drop >= 20 else None


def grid_outages(series, min_volts=150, max_gap=MAX_GAP):
    """Utility outages seen by the inverter: consecutive samples with grid voltage below `min_volts`."""
    out, start, last = [], None, None
    for t, d in series:
        if d['grid_v'] is None:
            continue
        down = d['grid_v'] < min_volts
        if down and start is None:
            start = t
        elif start is not None and (not down or (t - last).total_seconds() > max_gap):
            out.append({'start': start, 'end': last if down else t, 'minutes': round(((last if down else t) - start).total_seconds() / 60)})
            start = t if down else None
        last = t
    if start is not None:
        out.append({'start': start, 'end': None, 'minutes': round((last - start).total_seconds() / 60)})
    return out


def insights(series, now=None):
    now = now or datetime.now(timezone.utc)
    alerts = []
    recent = [(t, d) for t, d in series if t >= now - timedelta(days=7)]
    for name, other in (('pv1', 'pv2'), ('pv2', 'pv1')):
        dead = [t for t, d in recent if (d[f'{name}_v'] or 0) < 20 and (d[f'{other}_v'] or 0) > 150
                and (d[f'{other}_w'] or 0) > 300]
        sunny = [t for t, d in recent if (d[f'{other}_w'] or 0) > 300]
        if sunny and len(dead) / len(sunny) > 0.2:
            alerts.append({'level': 'warning', 'code': f'{name}_offline',
                           'text': f'String {name.upper()} sin tensión en {round(100 * len(dead) / len(sunny))} % de las lecturas con sol '
                                   f'en el otro string (7 días). Revisa seccionador, fusibles y conectores MC4.',
                           'last': max(dead)})
    disconnected = [t for t, d in recent if d['battery_disconnected']]
    if disconnected:
        alerts.append({'level': 'warning', 'code': 'battery_disconnected',
                       'text': f'{len(disconnected)} lecturas con la batería desconectada o sin comunicación BMS (SOC 0 % / <40 V) en 7 días.',
                       'last': max(disconnected)})
    full = [t for t, d in series if (d['soc'] or 0) >= 99]
    days_since_full = (now - max(full)).days if full else None
    if series and (days_since_full is None and (now - series[0][0]).days >= 10 or (days_since_full or 0) >= 10):
        alerts.append({'level': 'info', 'code': 'no_full_charge',
                       'text': 'La batería no llega al 100 % hace 10 días o más: el BMS no balancea celdas ni recalibra el SOC. '
                               'Conviene una carga de calibración: una noche con el cargador en “solar + red” hasta 100 %, y luego volver a “solo solar”.',
                       'last': max(full) if full else None})
    hot = [t for t, d in recent if (d['inner_temp'] or 0) >= 60 or (d['max_temp'] or 0) >= 70]
    if hot:
        alerts.append({'level': 'warning', 'code': 'temperature',
                       'text': 'Temperatura interna del inversor elevada: revisa ventilación.', 'last': max(hot)})
    faults = [t for t, d in recent if (d['fault'] or 0) != 0 or d['warning'] not in (None, '', '0', 0, [], {}, '[]', '{}')]
    if faults:
        alerts.append({'level': 'warning', 'code': 'fault', 'text': 'El inversor reportó fallas o advertencias.',
                       'last': max(faults)})
    gaps = [(b[0] - a[0]) for a, b in zip(recent, recent[1:]) if (b[0] - a[0]).total_seconds() > 1800]
    if gaps:
        alerts.append({'level': 'info', 'code': 'gaps',
                       'text': f'{len(gaps)} cortes de datos mayores a 30 min en 7 días (el mayor: {round(max(gaps).total_seconds() / 3600, 1)} h).',
                       'last': None})
    outages = grid_outages([(t, d) for t, d in series if t >= now - timedelta(days=30)])
    if outages:
        longest = max(o['minutes'] for o in outages)
        alerts.append({'level': 'info', 'code': 'grid_outage',
                       'text': f'{len(outages)} cortes de luz de la red en 30 días (el más largo: {longest} min). '
                               'Se registran para ajustar la reserva por temporal.',
                       'last': max(o['start'] for o in outages)})
    if series and (now - series[-1][0]).total_seconds() > 3600:
        alerts.append({'level': 'warning', 'code': 'stale',
                       'text': 'No hay datos del inversor en la última hora: revisa el recolector o la conexión del equipo.',
                       'last': series[-1][0]})
    return {'alerts': alerts, 'days_since_full_charge': days_since_full, 'grid_outages': outages[-20:]}


BUCKETS = (300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800)


def field_series(field, start, end, points=1200, db=None):
    """One variable, bucketed server-side so long ranges show the whole period.

    Derived names: pvTotal, gridImport (real import: line mode only)."""
    derived = {'pvTotal': 'pv_w', 'gridImport': 'grid_import_w'}.get(field)
    if derived:
        values = [(t, d[derived]) for t, d in samples(start, end, db)]
    else:
        sql = '''SELECT DISTINCT ON (observed_at) observed_at, payload->>%s AS value
          FROM measurements WHERE source IN ('history','realtime') AND observed_at >= %s AND observed_at < %s
          ORDER BY observed_at, (source='history') DESC, id DESC'''
        def run(database):
            return database.execute(sql, (field, start, end)).fetchall()
        rows = run(db) if db is not None else _with_db(run)
        values = [(r['observed_at'], num(r['value'])) for r in rows]
    if field in ('batteryCapacity', 'batteryVoltage'):
        values = [(t, v) for t, v in values if v is not None and (v > 0 if field == 'batteryCapacity' else v >= 40)]
    span = (end - start).total_seconds()
    bucket = next((b for b in BUCKETS if span / b <= points), BUCKETS[-1])
    if len(values) <= points:
        bucket = 0
    out = []
    if bucket:
        groups = defaultdict(list)
        for t, v in values:
            if v is not None:
                groups[int(t.timestamp()) // bucket * bucket].append(v)
        for key in sorted(groups):
            g = groups[key]
            out.append([datetime.fromtimestamp(key + bucket / 2, timezone.utc).isoformat(), sum(g) / len(g), min(g), max(g)])
    else:
        out = [[t.isoformat(), v, v, v] for t, v in values if v is not None]
    return {'field': field, 'bucket_seconds': bucket, 'points': out}


# ---------------------------------------------------------------- strategy study

_cache = {}


def env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def system_from_env(capacity=None):
    return System(capacity_kwh=capacity or env_float('BATTERY_KWH', '15.36'),
                  pv_kwp=sum(plane_kwps()), ac_limit_kw=env_float('PV_AC_LIMIT_KW', '8'),
                  performance_ratio=env_float('PV_PERFORMANCE_RATIO', '0.80'))


def plane_kwps():
    from weather import planes
    return [p['kwp'] for p in planes()]


def pv_kw_from_weather(payload, system, kwps=None):
    """Modelled AC kW from a weather payload, per string plane when available."""
    kwps = kwps or plane_kwps()
    per_plane = [num(payload.get(f'gti_pv{i + 1}')) for i in range(len(kwps))]
    temp = num(payload.get('temperature_2m'))
    if all(v is not None for v in per_plane):
        return pv_from_planes(list(zip(per_plane, kwps)), temp, system)
    irradiance = num(payload.get('global_tilted_irradiance'))
    if irradiance is None:
        irradiance = num(payload.get('shortwave_radiation'))  # conservative fallback
    return pv_from_irradiance(irradiance, temp, system)


def load_model(series):
    """Measured hourly shape and daily kWh by month; modelled seasonal factor elsewhere."""
    zone = tz()
    hourly = defaultdict(list)
    for t, d in series:
        if d['load_w'] is not None:
            hourly[t.astimezone(zone).hour].append(d['load_w'])
    if len(hourly) == 24 and all(len(v) >= 6 for v in hourly.values()):
        shape = [sum(hourly[h]) / len(hourly[h]) for h in range(24)]
    else:
        shape = list(LOAD_SHAPE)
    total = sum(shape)
    shape = [v / total for v in shape]
    days = [d for d in daily_energy(series) if d['covered_hours'] >= 20]
    by_month = defaultdict(list)
    for d in days:
        by_month[int(d['date'][5:7])].append(d['load_kwh'] * 24 / d['covered_hours'])
    measured = {m: sum(v) / len(v) for m, v in by_month.items() if len(v) >= 2}
    extra = env_float('LOAD_WINTER_EXTRA', '0.25')
    if measured:
        base = sum(measured[m] / seasonal_load_factor(m, extra) for m in measured) / len(measured)
    else:
        base = env_float('LOAD_DAILY_KWH', '14')
    monthly = {m: measured.get(m, base * seasonal_load_factor(m, extra)) for m in range(1, 13)}
    return shape, monthly, {m: True for m in measured}


def candidate_strategies():
    floor = int(env_float('BATTERY_MIN_SOC', '20'))
    fixed = [(floor, floor + 10), (floor, floor + 30), (30, 40), (40, 50)]
    out = [Strategy.fixed(a, b) for a, b in dict.fromkeys(fixed)]
    out += [Strategy.seasonal((floor, floor + 10), (40, 50)), Strategy.seasonal((floor, floor + 10), (30, 40))]
    for months, label in (((5, 6, 7, 8), 'may–ago'), ((6, 7), 'jun–jul')):
        strategy = Strategy.seasonal((floor, floor + 10), (40, 50), summer_months=tuple(m for m in range(1, 13) if m not in months))
        strategy.name = f'{floor}/{floor + 10} · 40/50 {label}'
        out.append(strategy)
    calibrate = Strategy.fixed(floor, floor + 10)
    calibrate.calibrate_days, calibrate.name = 10, f'{floor}/{floor + 10} + carga de calibración desde red (10 días)'
    grid = Strategy.fixed(floor, floor + 10)
    grid.grid_charge_kw, grid.name = 3.0, f'{floor}/{floor + 10} + la red carga la batería'
    return out + [calibrate, grid]


def full_charge_stats(days, trace, winter=(6, 7)):
    """Share of winter days reaching ~100 % and the typical/worst yearly streak without it."""
    daily = {}
    for day, soc in zip(days, trace):
        daily[day] = max(daily.get(day, 0), soc)
    streak, worst, hits, total = 0, defaultdict(int), 0, 0
    for day in sorted(daily):
        full = daily[day] >= 98
        streak = 0 if full else streak + 1
        worst[day.year] = max(worst[day.year], streak)
        if day.month in winter:
            hits, total = hits + full, total + 1
    streaks = sorted(worst.values())
    return {'winter_full_days': round(hits / total, 3) if total else None,
            'streak_typical_days': streaks[len(streaks) // 2] if streaks else None,
            'streak_worst_days': streaks[-1] if streaks else None}


def strategy_study(series=None, current=None, now=None):
    """Simulate SOC thresholds over the archived climate with the measured load."""
    key = int((now or time.time()) // 3600)
    if key in _cache:
        return _cache[key]
    with connect() as db:
        from weather import weather_id
        climate = db.execute('''SELECT observed_at,gti,ghi,temperature,gti_planes FROM climate_hourly
          WHERE location=%s ORDER BY observed_at''', (weather_id(),)).fetchall()
        if series is None:
            series = samples(datetime(2000, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc), db)
    if len(climate) < 24 * 365:
        return {'ready': False, 'reason': 'Descargando la climatología horaria de Valdivia; vuelve a intentar en unos minutos.',
                'climate_hours': len(climate)}
    measured_capacity = estimate_capacity_kwh(series)
    system = system_from_env()  # nameplate; the SOC-based estimate is reported, not simulated
    shape, monthly, measured_months = load_model(series)
    zone, kwps = tz(), plane_kwps()
    steps, days = [], []
    for row in climate:
        local = row['observed_at'].astimezone(zone)
        days.append((local - timedelta(hours=1)).date())
        planes = row['gti_planes']
        if planes and len(planes) == len(kwps) and all(v is not None for v in planes):
            pv = pv_from_planes(list(zip(planes, kwps)), row['temperature'], system)
        else:
            pv = pv_from_irradiance(row['gti'] if row['gti'] is not None else row['ghi'], row['temperature'], system)
        # Archive values average the preceding hour; attribute them to that hour.
        hour = (local.hour - 1) % 24
        steps.append((local.month, pv, monthly[local.month] * shape[hour]))
    years = len(steps) / 8766
    tariff, wear = env_float('GRID_TARIFF_CLP_KWH', '230'), env_float('BATTERY_WEAR_CLP_KWH', '45')
    strategies = candidate_strategies()
    if current and current.get('to_grid_soc') is not None and current.get('to_battery_soc') is not None:
        strategies.insert(0, Strategy.fixed(int(round(current['to_grid_soc'])), int(round(current['to_battery_soc']))))
        strategies[0].name += ' (actual)'
    results = []
    for strategy in strategies:
        trace = []
        total, months = simulate(steps, system, strategy, trace=trace)
        results.append({'name': strategy.name, 'low': strategy.low, 'high': strategy.high,
                        **full_charge_stats(days, trace),
                        'life': battery_life(total, years, temp_c=env_float('BATTERY_TEMP_C', '20'),
                                             calendar_pct_year=env_float('BATTERY_CALENDAR_PCT_YEAR', '1.5'),
                                             cycles_to_80=env_float('BATTERY_CYCLES_TO_80', '6000')),
                        'grid_charged_kwh_year': round(total['grid_charged'] / years),
                        'grid_kwh_year': round(total['grid'] / years), 'cycles_year': round(total['cycles'] / years),
                        'transfers_year': round(total['transfers'] / years),
                        'self_sufficiency': round(total['self_sufficiency'], 3),
                        'cost_clp_year': round(cost(total, years, tariff, wear)),
                        'grid_kwh_month': {m: round(v['grid'] / years) for m, v in sorted(months.items())}})
    best = min(results, key=lambda r: r['cost_clp_year'])
    pv_month = defaultdict(float)
    for month, pv, _ in steps:
        pv_month[month] += pv
    study = {'ready': True, 'years': round(years, 1), 'climate_from': climate[0]['observed_at'],
             'climate_to': climate[-1]['observed_at'],
             'planes': __import__('weather').planes(),
             'system': {'capacity_kwh': system.capacity_kwh, 'capacity_measured_kwh': measured_capacity,
                        'pv_kwp': system.pv_kwp, 'ac_limit_kw': system.ac_limit_kw,
                        'performance_ratio': system.performance_ratio},
             'load_daily_kwh': {m: round(v, 1) for m, v in monthly.items()}, 'load_measured_months': sorted(measured_months),
             'pv_daily_kwh': {m: round(v / years / days, 1) for m, v, days in
                              ((m, pv_month[m], (31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[m - 1]) for m in range(1, 13))},
             'tariff_clp_kwh': tariff, 'wear_clp_kwh': wear, 'results': results, 'best': best['name']}
    _cache.clear()
    _cache[key] = study
    return study


def forecast(db=None):
    """Expected PV per local day from the stored forecast (GTI on the panel plane)."""
    from weather import weather_id
    def run(database):
        return database.execute('''SELECT valid_at,payload FROM weather_forecast WHERE location=%s
          AND valid_at>now() ORDER BY valid_at''', (weather_id(),)).fetchall()
    rows = run(db) if db is not None else _with_db(run)
    system, zone, kwps = system_from_env(), tz(), plane_kwps()
    days = defaultdict(lambda: {'pv_kwh': 0.0, 'hours': 0, 'cloud': [], 'wind': 0.0, 'gust': 0.0, 'rain': 0.0})
    for row in rows:
        p = row['payload']
        day = days[(row['valid_at'] - timedelta(hours=1)).astimezone(zone).date().isoformat()]
        day['pv_kwh'] += pv_kw_from_weather(p, system, kwps)
        day['hours'] += 1
        if num(p.get('cloud_cover')) is not None:
            day['cloud'].append(num(p.get('cloud_cover')))
        day['wind'] = max(day['wind'], num(p.get('wind_speed_10m')) or 0)
        day['gust'] = max(day['gust'], num(p.get('wind_gusts_10m')) or 0)
        day['rain'] += num(p.get('precipitation')) or 0
    return [{'date': k, 'pv_kwh': round(v['pv_kwh'], 1), 'hours': v['hours'],
             'cloud_cover': round(sum(v['cloud']) / len(v['cloud'])) if v['cloud'] else None,
             'wind_max_kmh': round(v['wind']), 'gust_max_kmh': round(v['gust']),
             'precipitation_mm': round(v['rain'], 1)}
            for k, v in sorted(days.items())]
