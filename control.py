"""Automatic battery settings through the i.Solar cloud (opt-in, guarded).

Only these settings are ever written (see cloud.SETTING_COMMAND):
  BCRC -> PBCCnnn    SOC % at which the inverter goes back to the grid
  BCRD -> PBDCnnn    SOC % at which it goes back to the battery
  PC   -> PCP0n      charger priority (1 solar first, 2 solar + utility, 3 solar only)
  MCC  -> MNCHGCnnn  total battery charge current (A, program 02)
  MCG  -> MUCHGCnnn  utility charge current (A, program 11)

Grid charging (charger 1 or 2) is only ever enabled with BOTH current limits at or
below CONTROL_GRID_CHARGE_CAP_A: some Voltronic units ignore program 11 and charge
from the utility up to program 02, which could trip the house supply breaker.

Modes (CONTROL_MODE): off (default, nothing runs), dry-run (decides and logs,
never sends), on (sends, then reads back to verify). In "on" the panel switch
must also be enabled. Any setting changed outside this service pauses it.
"""
import os
import time
from datetime import datetime, timedelta, timezone
from psycopg.types.json import Jsonb
import analysis
from cloud import Cloud, CloudError, SETTING_COMMAND
from storage import connect, event, init

KEYS = {'to_grid': 'BCRC', 'to_battery': 'BCRD', 'charger': 'PC', 'charge_a': 'MCC', 'grid_charge_a': 'MCG'}
CHARGER = {1: 'solar primero', 2: 'solar + red', 3: 'solo solar'}
GRID_CHARGERS = (1, 2)  # priorities that let the utility charge the battery


def apply_rules(cfg, rules):
    """Panel-edited rules (stored in the database) override the .env defaults."""
    if not rules:
        return cfg
    cfg = dict(cfg)
    if rules.get('base'):
        cfg['base'] = tuple(rules['base'])
    if rules.get('winter') is False:
        cfg['winter_months'] = set()
    if 'storm' in rules:
        cfg['storm'] = bool(rules['storm'])
    return cfg


def env_pair(name, default):
    low, high = os.getenv(name, default).split('/')
    return int(low), int(high)


def config():
    months = os.getenv('CONTROL_WINTER_MONTHS', '6,7')
    return {
        'mode': os.getenv('CONTROL_MODE', 'off'),
        'base': env_pair('CONTROL_BASE', '20/30'),
        'winter': env_pair('CONTROL_WINTER', '40/50'),
        'winter_months': {int(m) for m in months.split(',') if m.strip()},
        'storm': os.getenv('CONTROL_STORM', '1') == '1',
        # SEC outage records for Valdivia 2025-2026 vs forecast gusts: days with >= 2000 customers
        # out go from ~3 % below 50 km/h to 12-14 % at 50-70 and >= 50 % above 70. A 60 km/h trigger
        # fires ~13 days/year and anticipates 6 of 29 large-outage days; each reserve day costs
        # ~0.2 kWh. Rain alone showed no large outages (>= 60 mm: 0 of 5 days), so it is off.
        'storm_gust_kmh': float(os.getenv('CONTROL_STORM_GUST_KMH', '60')),
        'storm_rain_mm': float(os.getenv('CONTROL_STORM_RAIN_MM', '0')),
        # Off by default: on some Voltronic units the utility charge limit (MCG, program 11) is
        # ignored and grid charging follows the total limit (MCC, program 02), which could exceed
        # the house supply. Enable only after a supervised test of the real grid draw.
        'calibration': os.getenv('CONTROL_CALIBRATION', '0') == '1',
        'calibration_days': int(os.getenv('CONTROL_CALIBRATION_DAYS', '10')),
        'charger': int(os.getenv('CONTROL_CHARGER', '3')),
        'min_soc': int(os.getenv('CONTROL_MIN_SOC', '15')),
        'max_commands_day': int(os.getenv('CONTROL_MAX_COMMANDS_DAY', '12')),
        'interval': int(os.getenv('CONTROL_INTERVAL_SECONDS', '900')),
        'max_data_age_min': int(os.getenv('CONTROL_MAX_DATA_AGE_MIN', '30')),
        # Empty = keep the installer's value. Battery label: 150 A recommended, 200 A max.
        'max_charge_a': int(os.getenv('CONTROL_MAX_CHARGE_A')) if os.getenv('CONTROL_MAX_CHARGE_A') else None,
        'battery_max_a': int(os.getenv('CONTROL_BATTERY_MAX_A', '200')),
        'grid_charge_idle_a': int(os.getenv('CONTROL_GRID_CHARGE_IDLE_A', '2')),
        # 30 A DC ~ 1.6 kW ~ 8 A AC: with a 40 A supply and a 32 A house breaker the worst case stays <= 40 A.
        'grid_charge_cap_a': int(os.getenv('CONTROL_GRID_CHARGE_CAP_A', '30')),
        'grid_charge_a': min(int(os.getenv('CONTROL_GRID_CHARGE_A', '30')), int(os.getenv('CONTROL_GRID_CHARGE_CAP_A', '30'))),
        'grid_import_max_w': float(os.getenv('CONTROL_GRID_IMPORT_MAX_W', '7000')),
    }


def parse_param(raw):
    """'20 5~50', '3 1,2,3', '2 2,10~180' -> value plus allowed options/ranges and overall min/max."""
    if raw is None:
        return None
    parts = str(raw).split(' ')
    try:
        value = float(parts[0])
    except ValueError:
        return None
    out = {'value': int(value) if value.is_integer() else value}
    options, ranges = [], []
    for piece in (parts[1].split(',') if len(parts) > 1 else []):
        try:
            if '~' in piece:
                low, high = piece.split('~')[:2]
                ranges.append((float(low), float(high)))
            elif piece.strip():
                options.append(int(float(piece)))
        except ValueError:
            continue
    if options:
        out['options'] = options
    if ranges:
        out['ranges'] = ranges
    bounds = options + [v for r in ranges for v in r]
    if bounds:
        out.update(min=min(bounds), max=max(bounds))
    return out


def allowed(value, info):
    if not info or not (info.get('options') or info.get('ranges')):
        return True
    return value in info.get('options', []) or any(lo <= value <= hi for lo, hi in info.get('ranges', []))


def current_settings(params):
    out = {name: parse_param(params.get(key)) for name, key in KEYS.items()}
    battery_type = str(params.get('BT', '')).split(' ')[0]
    # The portal shows SOC thresholds only for battery types other than 0/1/2 (lead-acid/user).
    out['soc_mode'] = bool(out['to_grid'] and out['to_battery']) and battery_type[:1] not in ('0', '1', '2')
    out['battery_type'] = battery_type
    return out


def storm_ahead(forecast, cfg, now=None):
    zone = analysis.tz()
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    for day in forecast:
        if day['date'] in (today.isoformat(), (today + timedelta(days=1)).isoformat()):
            rain = cfg['storm_rain_mm'] > 0 and day['precipitation_mm'] >= cfg['storm_rain_mm']
            if day.get('gust_max_kmh', 0) >= cfg['storm_gust_kmh'] or rain:
                return day
    return None


def safe_currents(target, cfg):
    """Grid-capable charger priorities always run with both current limits at the safe cap."""
    if target['charger'] in GRID_CHARGERS:
        target['charge_a'] = min(target.get('charge_a') or cfg['grid_charge_a'], cfg['grid_charge_a'])
        target['grid_charge_a'] = cfg['grid_charge_a']
    return target


def desired(cfg, now, insight, forecast, calibration_started, calibration_done, hold=None, keep=None):
    """Target settings and the reason, from the season, the forecast and the BMS state.

    `hold` is a manual request from the panel that stays in force until its `hold_until`.
    `keep` holds the current limits to restore (pre-calibration values) when not configured.
    """
    keep = keep or {}
    currents = {'charge_a': cfg['max_charge_a'] or keep.get('charge_a'), 'grid_charge_a': cfg['grid_charge_idle_a']}
    if hold and hold.get('hold_until') and datetime.fromisoformat(hold['hold_until']) > now:
        return safe_currents({**currents, **{k: hold[k] for k in ('to_grid', 'to_battery', 'charger')},
                              'calibrating': False, 'hold_until': hold['hold_until'],
                              'reason': f'Ajuste manual vigente hasta {datetime.fromisoformat(hold["hold_until"]).astimezone(analysis.tz()):%d-%m %H:%M}'}, cfg)
    zone = analysis.tz()
    local = now.astimezone(zone)
    low, high = cfg['base']
    reason = f'Base {low}/{high}'
    if local.month in cfg['winter_months']:
        low, high = cfg['winter']
        reason = f'Invierno ({low}/{high} en meses {",".join(map(str, sorted(cfg["winter_months"])))})'
    storm = storm_ahead(forecast, cfg, now) if cfg['storm'] else None
    if storm:
        low, high = max(low, cfg['winter'][0]), max(high, cfg['winter'][1])
        reason = f'Reserva por temporal {storm["date"]} (ráfagas {storm.get("gust_max_kmh", 0)} km/h)'
    target = {'to_grid': low, 'to_battery': high, 'charger': cfg['charger'], 'reason': reason, 'calibrating': False,
              **currents}
    days = insight.get('days_since_full_charge')
    # Grid charging is a night-time job: from 18-23 h until full (45 min >= 99 %) or 08:00.
    if cfg['calibration'] and calibration_started is not None:
        daytime = 8 <= local.hour < 18
        if not (calibration_done or daytime or now - calibration_started > timedelta(hours=16)):
            target.update(to_battery=100, charger=2, calibrating=True,
                          reason=f'Carga de calibración en curso (desde {calibration_started.astimezone(zone):%d-%m %H:%M})')
    elif cfg['calibration'] and days is not None and days >= cfg['calibration_days'] and 18 <= local.hour < 23:
        target.update(to_battery=100, charger=2, calibrating=True,
                      reason=f'Carga de calibración: {days} días sin llegar al 100 %')
    return safe_currents(target, cfg)


def validate(target, current, cfg):
    """Clamp-free validation: refuse anything outside the device range or the safety floor."""
    problems = []
    if not current['soc_mode']:
        problems.append('El inversor no informa umbrales por SOC (tipo de batería sin comunicación).')
        return problems
    for name in ('to_grid', 'to_battery'):
        value, info = target[name], current[name]
        if info.get('min') is not None and not (info['min'] <= value <= info['max']):
            problems.append(f'{KEYS[name]}={value} fuera del rango del equipo {info["min"]:g}–{info["max"]:g}.')
        if value % 5:
            problems.append(f'{KEYS[name]}={value} no es múltiplo de 5.')
    if target['to_grid'] < cfg['min_soc']:
        problems.append(f'Vuelta a red {target["to_grid"]} % bajo el mínimo de seguridad {cfg["min_soc"]} %.')
    if target['to_grid'] > 60:
        problems.append('Vuelta a red sobre 60 % no tiene sentido para esta batería.')
    if target['to_battery'] < target['to_grid'] + 5:
        problems.append('La vuelta a batería debe superar la vuelta a red en al menos 5 puntos.')
    charger = current.get('charger') or {}
    if target['charger'] not in CHARGER or (charger.get('options') and target['charger'] not in charger['options']):
        problems.append(f'Prioridad de cargador {target["charger"]} no disponible.')
    for name in ('charge_a', 'grid_charge_a'):
        value, info = target.get(name), current.get(name)
        if value is None or info is None:
            continue
        if not allowed(value, info):
            problems.append(f'{KEYS[name]}={value} A no lo acepta el equipo.')
    if target.get('charge_a') is not None and not (10 <= target['charge_a'] <= cfg['battery_max_a']):
        problems.append(f'Corriente de carga {target["charge_a"]} A fuera de 10–{cfg["battery_max_a"]} A (límite de la batería).')
    if target['charger'] in GRID_CHARGERS:
        if current.get('charge_a') is None or current.get('grid_charge_a') is None:
            problems.append('El equipo no informa MCC/MCG: no se habilita la carga desde la red.')
        elif target['charge_a'] > cfg['grid_charge_cap_a'] or target['grid_charge_a'] > cfg['grid_charge_cap_a']:
            problems.append(f'Carga desde la red solo con MCC y MCG ≤ {cfg["grid_charge_cap_a"]} A (empalme de la vivienda).')
    return problems


def plan(target, current):
    """Commands in a safe order: currents are lowered before grid charging is enabled,
    and grid charging is disabled before currents are raised again."""
    def differs(name):
        return target.get(name) is not None and (current.get(name) or {}).get('value') != target[name]
    thresholds = [f'PBCC{target["to_grid"]:03d}'] if differs('to_grid') else []
    thresholds += [f'PBDC{target["to_battery"]:03d}'] if differs('to_battery') else []
    charger = [f'PCP0{target["charger"]}'] if differs('charger') else []
    total = [f'MNCHGC{target["charge_a"]:03d}'] if differs('charge_a') else []
    grid = [f'MUCHGC{target["grid_charge_a"]:03d}'] if differs('grid_charge_a') else []
    if target['charger'] in GRID_CHARGERS:
        commands = total + grid + charger + thresholds
    else:
        commands = charger + grid + total + thresholds
    assert all(SETTING_COMMAND.fullmatch(c) for c in commands)
    return commands


def snapshot(current):
    return {k: (current.get(k) or {}).get('value') for k in KEYS}


def same(a, b):
    """Compare only the settings both sides know (older targets lack the current limits)."""
    return all(a.get(k) == b.get(k) for k in KEYS if a.get(k) is not None and b.get(k) is not None)


def state(db):
    return db.execute('SELECT * FROM control_state WHERE id=1').fetchone()


def commands_today(db):
    return db.execute('''SELECT coalesce(sum(jsonb_array_length(commands)),0) AS n FROM control_actions
      WHERE mode='on' AND time > now() - interval '24 hours' ''').fetchone()['n']


def log_action(db, mode, reason, commands, before, code=None, verified=None, after=None, error=None):
    return db.execute('''INSERT INTO control_actions(mode,reason,commands,before,response_code,verified,after,error)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
      (mode, reason, Jsonb(commands), Jsonb(before), code, verified, Jsonb(after) if after else None, error)).fetchone()['id']


def logged_recently(db, error, minutes=60):
    return db.execute('''SELECT 1 FROM control_actions WHERE error=%s AND time > now() - %s * interval '1 minute' LIMIT 1''',
                      (error, minutes)).fetchone() is not None


def verify(client, sn, target, tries=10, wait=60, sleep=time.sleep, keys=None):
    """Poll the device until it reports the requested values (the cloud relays commands asynchronously)."""
    current = None
    wanted = {k: target.get(k) for k in (keys or KEYS)}
    for _ in range(tries):
        sleep(wait)
        current = current_settings(client.params(sn))
        if same(snapshot(current), wanted):
            return True, current
    return False, current


def step(client, sn, cfg=None, now=None, sleep=time.sleep):
    """One control cycle. Returns a short status string (also stored as an event when relevant)."""
    cfg = cfg or config()
    now = now or datetime.now(timezone.utc)
    if cfg['mode'] not in ('dry-run', 'on'):
        return 'Control apagado (CONTROL_MODE=off).'
    current = current_settings(client.params(sn))
    try:
        link = client.device_status(sn)
    except (CloudError, AttributeError):
        link = {'online': None, 'updated': None}
    series = analysis.samples(now - timedelta(days=30), now)
    insight = analysis.insights(series, now)
    # Calibration ends after 45 min at >= 99 % so the BMS can top-balance the cells.
    tail = [d['soc'] for t, d in series if t >= now - timedelta(minutes=45)]
    calibration_done = len(tail) >= 3 and all(v is not None and v >= 99 for v in tail)
    with connect() as db:
        st = state(db)
        cfg = apply_rules(cfg, st.get('rules'))
        db.execute('UPDATE control_state SET last_params=%s, params_at=now(), updated_at=now() WHERE id=1',
                   (Jsonb(snapshot(current) | {'soc_mode': current['soc_mode'], 'battery_type': current['battery_type'],
                                                'ranges': {k: current[k] for k in KEYS},
                                                'cloud_online': link['online'], 'cloud_updated': link['updated']}),))
        request = st['request']
    # A manual change (inverter screen, portal, app) wins: pause until re-enabled from the panel.
    last = st['last_target']
    if cfg['mode'] == 'on' and st['enabled'] and last and not same(snapshot(current), last):
        with connect() as db:
            db.execute('UPDATE control_state SET enabled=false, paused_reason=%s, last_target=NULL WHERE id=1',
                       ('Se detectó un cambio manual de los ajustes; automatización en pausa.',))
        event(False, 'Control: cambio manual detectado, automatización en pausa')
        return 'Cambio manual detectado: en pausa.'
    # Emergency stop: while the grid may charge the battery, check the live grid draw.
    abort = None
    if cfg['mode'] == 'on' and st['calibration_started'] is not None:
        try:
            live = client.realtime(sn)
            from storage import save
            save(sn, 'realtime', live, {'deviceSn': sn})
            draw = analysis.derive(live['data']).get('grid_import_w') or 0
        except (CloudError, KeyError, TypeError):
            draw = 0
        if draw > cfg['grid_import_max_w']:
            abort = f'Corte de emergencia: la red entregaba {draw:.0f} W (> {cfg["grid_import_max_w"]:.0f} W) durante la carga desde la red'
    keep = st['pre_calibration'] or snapshot(current)
    effective = cfg | {'calibration': False} if abort or st['calibration_blocked'] else cfg
    target = desired(effective, now, insight, analysis.forecast(), None if abort else st['calibration_started'],
                     calibration_done, st['last_target'], keep)
    if abort:
        target['reason'] = abort
    requested_at = datetime.fromisoformat(request['requested_at']) if request and request.get('requested_at') else now
    if request and now - requested_at > timedelta(hours=12):
        with connect() as db:
            db.execute('UPDATE control_state SET request=NULL WHERE id=1')
            log_action(db, cfg['mode'], 'Solicitud manual: ' + request.get('label', ''), [], snapshot(current),
                       error='Solicitud vencida: el equipo no estuvo disponible en 12 h')
        request = None
    if request:
        hours = min(max(int(request.get('hours', 24)), 1), 24 * 14)
        target = safe_currents({**target, **{k: request[k] for k in ('to_grid', 'to_battery', 'charger') if k in request},
                                'calibrating': False, 'hold_until': (now + timedelta(hours=hours)).isoformat(),
                                'reason': f'Solicitud manual desde el panel: {request.get("label", "")} ({hours} h)'}, cfg)
    problems = validate(target, current, cfg)
    commands = plan(target, current) if not problems else []
    with connect() as db:
        def done_with_request():
            if request:
                db.execute('UPDATE control_state SET request=NULL WHERE id=1')

        def waiting(error):
            # Offline/stale device: keep a panel request pending; log once per hour, not every minute.
            if request and not request.get('waiting'):
                db.execute('UPDATE control_state SET request=%s WHERE id=1', (Jsonb(request | {'waiting': True}),))
            if not logged_recently(db, error):
                log_action(db, 'on', target['reason'], commands, snapshot(current), error=error)

        if problems:
            done_with_request()
            log_action(db, cfg['mode'], target['reason'], [], snapshot(current), error=' '.join(problems))
            return 'Rechazado: ' + ' '.join(problems)
        calibration = st['calibration_started']
        if target['calibrating'] and calibration is None:
            calibration = now
            db.execute('UPDATE control_state SET pre_calibration=%s WHERE id=1', (Jsonb(snapshot(current)),))
        elif not target['calibrating']:
            calibration = None
        db.execute('UPDATE control_state SET calibration_started=%s WHERE id=1', (calibration,))
        if abort:
            db.execute('UPDATE control_state SET calibration_blocked=%s WHERE id=1', (abort,))
        if not target['calibrating'] and st['pre_calibration'] and not commands:
            db.execute('UPDATE control_state SET pre_calibration=NULL WHERE id=1')
        if not commands:
            done_with_request()
            if cfg['mode'] == 'on' and st['enabled']:
                db.execute('UPDATE control_state SET last_target=%s WHERE id=1', (Jsonb(target),))
            return 'Sin cambios: ' + target['reason']
        if cfg['mode'] == 'dry-run' or not (st['enabled'] or request):
            done_with_request()
            # dry-run mode, or mode "on" with the automation paused: record what it would do,
            # once per decision rather than every cycle.
            mode = 'dry-run' if cfg['mode'] == 'dry-run' else 'paused'
            last_row = db.execute('SELECT mode,reason,commands FROM control_actions ORDER BY id DESC LIMIT 1').fetchone()
            if not (last_row and last_row['mode'] == mode and last_row['reason'] == target['reason']
                    and last_row['commands'] == commands):
                log_action(db, mode, target['reason'], commands, snapshot(current))
            return ('Simulación' if mode == 'dry-run' else 'Automatización en pausa') + ': enviaría ' + ', '.join(commands)
        if link['online'] is False:
            waiting('La nube marca el equipo offline: no acepta comandos aunque lleguen datos; se reintentará')
            return 'Equipo offline en la nube: no se envía' + (' (solicitud en espera).' if request else '.')
        # The cloud accepts commands for an offline datalogger but cannot deliver them (seen as 799011).
        last_seen = series[-1][0] if series else None
        if last_seen is None or now - last_seen > timedelta(minutes=cfg['max_data_age_min']):
            age = 'sin datos' if last_seen is None else f'último dato hace {int((now - last_seen).total_seconds() // 60)} min'
            waiting('Equipo sin conexión (sin datos recientes); se reintentará')
            return f'Equipo sin conexión ({age}): no se envía' + (' (solicitud en espera).' if request else '.')
        done_with_request()
        # Leaving grid charging (dawn, full battery or emergency stop) is never rate-limited.
        to_safety = abort or ((current.get('charger') or {}).get('value') in GRID_CHARGERS
                              and target['charger'] not in GRID_CHARGERS)
        if not to_safety and commands_today(db) + len(commands) > cfg['max_commands_day']:
            log_action(db, 'on', target['reason'], commands, snapshot(current), error='Límite diario de comandos alcanzado')
            return 'Límite diario de comandos alcanzado.'
    # Two stages when enabling grid charging: the current limits must be CONFIRMED by the
    # device before the charger priority lets the utility charge the battery.
    enabling_grid = (target['charger'] in GRID_CHARGERS
                     and (current.get('charger') or {}).get('value') not in GRID_CHARGERS)
    limits = [c for c in commands if c.startswith(('MNCHGC', 'MUCHGC'))]
    if enabling_grid and limits:
        print(f'Etapa 1: {", ".join(limits)} · verificando antes de habilitar la red…', flush=True)
        try:
            code, message = client.send_settings(sn, limits)
        except (CloudError, ValueError) as exc:
            code, message = 'error', str(exc)
        ok, seen = verify(client, sn, target, sleep=sleep, keys=('charge_a', 'grid_charge_a')) if code != 'error' else (False, None)
        if not ok:
            reason = (f'No se habilitó la carga desde la red: el equipo no confirmó {", ".join(limits)} '
                      f'(código {code}{": " + message if message else ""})')
            with connect() as db:
                log_action(db, 'on', target['reason'], limits, snapshot(current), code, False,
                           snapshot(seen) if seen else None, reason)
                db.execute('''UPDATE control_state SET enabled=false, last_target=NULL, calibration_started=NULL,
                  calibration_blocked=%s, paused_reason=%s WHERE id=1''', (reason, reason + '; automatización en pausa.'))
            event(False, 'Control: ' + reason)
            return reason
        with connect() as db:
            log_action(db, 'on', target['reason'] + ' · etapa 1 (corrientes)', limits, snapshot(current), code, True,
                       snapshot(seen))
        commands = [c for c in commands if c not in limits]
        current = seen
    print(f'Enviando {", ".join(commands)} · {target["reason"]} · verificando con el inversor (hasta 10 min)…', flush=True)
    try:
        code, message = client.send_settings(sn, commands)
    except (CloudError, ValueError) as exc:
        with connect() as db:
            log_action(db, 'on', target['reason'], commands, snapshot(current), error=str(exc))
        event(False, 'Control: envío fallido ' + str(exc))
        return 'Envío fallido.'
    # The cloud may answer with a timeout-like code while the device still applies the change:
    # the read-back is what counts, whatever the code.
    verified, after = verify(client, sn, target, sleep=sleep)
    detail = f'código {code}' + (f': {message}' if message else '')
    with connect() as db:
        log_action(db, 'on', target['reason'], commands, snapshot(current), code, verified,
                   snapshot(after) if after else None,
                   None if verified and code == '0' else (f'Confirmado leyendo el equipo ({detail})' if verified else f'Sin confirmar ({detail})'))
        if verified and abort:
            db.execute('UPDATE control_state SET enabled=false, last_target=NULL, paused_reason=%s WHERE id=1',
                       (abort + '; se restauró la configuración normal y la automatización quedó en pausa.',))
        elif verified:
            db.execute('UPDATE control_state SET last_target=%s, paused_reason=NULL WHERE id=1', (Jsonb(target),))
        else:
            db.execute('UPDATE control_state SET enabled=false, last_target=NULL, paused_reason=%s WHERE id=1',
                       (f'El equipo no confirmó {", ".join(commands)} ({detail}); automatización en pausa.',))
    event(verified, f'Control: {", ".join(commands)} · {target["reason"]}' + ('' if verified else ' · sin confirmar'))
    return ('Aplicado y verificado: ' if verified else 'Sin confirmar: ') + ', '.join(commands)


def run(stop=None):
    init()
    cfg = config()
    if cfg['mode'] not in ('dry-run', 'on'):
        print('Control apagado (CONTROL_MODE=off); el servicio queda inactivo.', flush=True)
    client = Cloud(os.environ['SOLAR_USERNAME'], os.environ['SOLAR_PASSWORD'])
    sn = os.environ['SOLAR_DEVICE_SN']
    print(f"Control iniciado · modo {cfg['mode']} · base {cfg['base'][0]}/{cfg['base'][1]} · invierno "
          f"{cfg['winter'][0]}/{cfg['winter'][1]} meses {sorted(cfg['winter_months'])} · ráfagas ≥ {cfg['storm_gust_kmh']:g} km/h · "
          f"calibración {'sí' if cfg['calibration'] else 'no'} · carga red {cfg['grid_charge_a']} A", flush=True)
    while stop is None or not stop.is_set():
        if cfg['mode'] in ('dry-run', 'on'):
            try:
                print(step(client, sn, cfg), flush=True)
            except Exception as exc:
                print('Error de control: ' + (str(exc) if isinstance(exc, CloudError) else type(exc).__name__), flush=True)
        # New panel requests are picked up within a minute; a request waiting for the device
        # to come back online is retried every 3 minutes; otherwise a full cycle every `interval`.
        for minute in range(1, max(1, cfg['interval'] // 60) + 1):
            if stop is not None and stop.wait(60):
                return
            if stop is None:
                time.sleep(60)
            with connect() as db:
                st = state(db)
            pending = st['request']
            if pending and (not pending.get('waiting') or minute % 3 == 0):
                break
            if st['calibration_started'] is not None and minute % 3 == 0:
                break  # watch the grid draw closely while the utility may charge


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Ajustes automáticos de batería vía i.Solar')
    parser.add_argument('--status', action='store_true', help='Solo lee y muestra los ajustes actuales (no envía nada)')
    parser.add_argument('--once', action='store_true', help='Un ciclo con el CONTROL_MODE configurado')
    parser.add_argument('--test-send', metavar='COMANDO', help='Prueba: envía UN comando de la lista blanca y verifica')
    parser.add_argument('--slot', type=int, default=1, help='Clave S0n con la que se envía la prueba (el portal usa S05 para MCC)')
    args = parser.parse_args()
    init()
    client = Cloud(os.environ['SOLAR_USERNAME'], os.environ['SOLAR_PASSWORD'])
    sn = os.environ['SOLAR_DEVICE_SN']
    if args.status:
        params = client.params(sn)
        current = current_settings(params)
        print('Tipo de batería (BT):', current['battery_type'], '· umbrales por SOC:', current['soc_mode'])
        link = client.device_status(sn)
        print('Conexión con la nube (acepta comandos):', {True: 'online', False: 'OFFLINE', None: 'desconocida'}[link['online']],
              '· última actualización:', link['updated'])
        print('Datalogger WiFi, versión:', link.get('wifi_version'), '· firmware equipo:', ', '.join(map(str, link.get('firmware') or [])) or '—')
        for name, key in KEYS.items():
            print(f'  {key:5s} {name:10s} {params.get(key)!r}')
        # Read-only: charge/discharge current limits vs the battery (150 A recommended, 200 A max).
        for key, label in (('MDC', 'corriente máx. de descarga (A)'), ('BCU', 'corte por SOC bajo (%)'),
                           ('EQ', 'ecualización (debe estar en 0 con LiFePO4)')):
            if key in params:
                print(f'  {key:5s} {label:42s} {params.get(key)!r}')
        print('Parámetros informados por el equipo:', ', '.join(sorted(params)))
        return
    if args.test_send:
        if not SETTING_COMMAND.fullmatch(args.test_send) or args.test_send.startswith('PCP0'):
            raise SystemExit('Solo se permite probar PBCC/PBDC/MNCHGC/MUCHGC (no la prioridad del cargador).')
        key = {'PBCC': 'BCRC', 'PBDC': 'BCRD', 'MNCH': 'MCC', 'MUCH': 'MCG'}[args.test_send[:4]]
        number = args.test_send[6:] if key in ('MCC', 'MCG') else args.test_send[4:]
        print('Antes:', key, client.params(sn).get(key))
        code, message = client.send_settings(sn, [args.test_send], slots=[args.slot])
        print(f'Enviado {{"S0{args.slot}":"{args.test_send}"}} · respuesta: código {code} {message}')
        for minute in range(1, 6):
            time.sleep(60)
            raw = client.params(sn).get(key)
            print(f'  {minute} min: {key} = {raw}', flush=True)
            if str(raw).split(' ')[0] == str(int(number)):
                print('Aplicado.')
                break
        else:
            print('No se aplicó en 5 minutos.')
        with connect() as db:
            log_action(db, 'on', f'Prueba manual {{"S0{args.slot}":"{args.test_send}"}}', [args.test_send], {}, code,
                       str(raw).split(' ')[0] == str(int(number)), None, message or None)
        return
    if args.once:
        print(step(client, sn))
        return
    run()


if __name__ == '__main__':
    main()
