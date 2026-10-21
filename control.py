"""Automatic battery settings through the i.Solar cloud (opt-in, guarded).

Only three settings are ever written (see cloud.SETTING_COMMAND):
  BCRC -> PBCCnnn  SOC % at which the inverter goes back to the grid
  BCRD -> PBDCnnn  SOC % at which it goes back to the battery
  PC   -> PCP0n    charger priority (1 solar first, 2 solar + utility, 3 solar only)

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

KEYS = {'to_grid': 'BCRC', 'to_battery': 'BCRD', 'charger': 'PC'}
CHARGER = {1: 'solar primero', 2: 'solar + red', 3: 'solo solar'}


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
        # Valdivia 2015-2025 outside June-July: gusts >= 70 km/h ~7 days/year, >= 80 km/h ~2.
        # Heavy rain alone does not cut the local grid (owner's experience), so rain is off by default
        # (CONTROL_STORM_RAIN_MM=0); mean wind >= 50 km/h practically never occurs.
        'storm_gust_kmh': float(os.getenv('CONTROL_STORM_GUST_KMH', '70')),
        'storm_rain_mm': float(os.getenv('CONTROL_STORM_RAIN_MM', '0')),
        'calibration': os.getenv('CONTROL_CALIBRATION', '1') == '1',
        'calibration_days': int(os.getenv('CONTROL_CALIBRATION_DAYS', '10')),
        'charger': int(os.getenv('CONTROL_CHARGER', '3')),
        'min_soc': int(os.getenv('CONTROL_MIN_SOC', '15')),
        'max_commands_day': int(os.getenv('CONTROL_MAX_COMMANDS_DAY', '6')),
        'interval': int(os.getenv('CONTROL_INTERVAL_SECONDS', '900')),
    }


def parse_param(raw):
    """'20 5~50' -> value/min/max; '3 1,2,3' -> value/options; '20' -> value."""
    if raw is None:
        return None
    parts = str(raw).split(' ')
    try:
        value = float(parts[0])
    except ValueError:
        return None
    out = {'value': int(value) if value.is_integer() else value}
    if len(parts) > 1 and '~' in parts[1]:
        low, high = parts[1].split('~')[:2]
        out.update(min=float(low), max=float(high))
    elif len(parts) > 1 and parts[1]:
        out['options'] = [int(float(o)) for o in parts[1].split(',') if o.strip().lstrip('-').replace('.', '').isdigit()]
    return out


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


def desired(cfg, now, insight, forecast, calibration_started, calibration_done, hold=None):
    """Target settings and the reason, from the season, the forecast and the BMS state.

    `hold` is a manual request from the panel that stays in force until its `hold_until`.
    """
    if hold and hold.get('hold_until') and datetime.fromisoformat(hold['hold_until']) > now:
        return {**{k: hold[k] for k in KEYS}, 'calibrating': False, 'hold_until': hold['hold_until'],
                'reason': f'Ajuste manual vigente hasta {datetime.fromisoformat(hold["hold_until"]).astimezone(analysis.tz()):%d-%m %H:%M}'}
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
    target = {'to_grid': low, 'to_battery': high, 'charger': cfg['charger'], 'reason': reason, 'calibrating': False}
    days = insight.get('days_since_full_charge')
    if cfg['calibration'] and calibration_started is not None:
        done = calibration_done
        expired = now - calibration_started > timedelta(hours=20)
        if not (done or expired):
            target.update(to_battery=100, charger=2, calibrating=True,
                          reason=f'Carga de calibración en curso (desde {calibration_started.astimezone(zone):%d-%m %H:%M})')
    elif cfg['calibration'] and days is not None and days >= cfg['calibration_days'] and 18 <= local.hour < 23:
        target.update(to_battery=100, charger=2, calibrating=True,
                      reason=f'Carga de calibración: {days} días sin llegar al 100 %')
    return target


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
    return problems


def plan(target, current):
    commands = []
    if current['to_grid']['value'] != target['to_grid']:
        commands.append(f'PBCC{target["to_grid"]:03d}')
    if current['to_battery']['value'] != target['to_battery']:
        commands.append(f'PBDC{target["to_battery"]:03d}')
    if (current.get('charger') or {}).get('value') != target['charger']:
        commands.append(f'PCP0{target["charger"]}')
    assert all(SETTING_COMMAND.fullmatch(c) for c in commands)
    return commands


def snapshot(current):
    return {k: (current.get(k) or {}).get('value') for k in KEYS}


def state(db):
    return db.execute('SELECT * FROM control_state WHERE id=1').fetchone()


def commands_today(db):
    return db.execute('''SELECT coalesce(sum(jsonb_array_length(commands)),0) AS n FROM control_actions
      WHERE mode='on' AND time > now() - interval '24 hours' ''').fetchone()['n']


def log_action(db, mode, reason, commands, before, code=None, verified=None, after=None, error=None):
    return db.execute('''INSERT INTO control_actions(mode,reason,commands,before,response_code,verified,after,error)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
      (mode, reason, Jsonb(commands), Jsonb(before), code, verified, Jsonb(after) if after else None, error)).fetchone()['id']


def verify(client, sn, target, tries=10, wait=60, sleep=time.sleep):
    """Poll the device until it reports the requested values (the cloud relays commands asynchronously)."""
    current = None
    for _ in range(tries):
        sleep(wait)
        current = current_settings(client.params(sn))
        if snapshot(current) == {k: target[k] for k in KEYS}:
            return True, current
    return False, current


def step(client, sn, cfg=None, now=None, sleep=time.sleep):
    """One control cycle. Returns a short status string (also stored as an event when relevant)."""
    cfg = cfg or config()
    now = now or datetime.now(timezone.utc)
    if cfg['mode'] not in ('dry-run', 'on'):
        return 'Control apagado (CONTROL_MODE=off).'
    current = current_settings(client.params(sn))
    series = analysis.samples(now - timedelta(days=30), now)
    insight = analysis.insights(series, now)
    # Calibration ends after 45 min at >= 99 % so the BMS can top-balance the cells.
    tail = [d['soc'] for t, d in series if t >= now - timedelta(minutes=45)]
    calibration_done = len(tail) >= 3 and all(v is not None and v >= 99 for v in tail)
    with connect() as db:
        st = state(db)
        db.execute('UPDATE control_state SET last_params=%s, params_at=now(), updated_at=now() WHERE id=1',
                   (Jsonb(snapshot(current) | {'soc_mode': current['soc_mode'], 'battery_type': current['battery_type'],
                                                'ranges': {k: current[k] for k in KEYS}}),))
        request = st['request']
    # A manual change (inverter screen, portal, app) wins: pause until re-enabled from the panel.
    last = st['last_target']
    if cfg['mode'] == 'on' and st['enabled'] and last and snapshot(current) != {k: last[k] for k in KEYS}:
        with connect() as db:
            db.execute('UPDATE control_state SET enabled=false, paused_reason=%s, last_target=NULL WHERE id=1',
                       ('Se detectó un cambio manual de los ajustes; automatización en pausa.',))
        event(False, 'Control: cambio manual detectado, automatización en pausa')
        return 'Cambio manual detectado: en pausa.'
    target = desired(cfg, now, insight, analysis.forecast(), st['calibration_started'], calibration_done, st['last_target'])
    if request:
        hours = min(max(int(request.get('hours', 24)), 1), 24 * 14)
        target = {**target, **{k: request[k] for k in KEYS if k in request}, 'calibrating': False,
                  'hold_until': (now + timedelta(hours=hours)).isoformat(),
                  'reason': f'Solicitud manual desde el panel: {request.get("label", "")} ({hours} h)'}
    problems = validate(target, current, cfg)
    commands = plan(target, current) if not problems else []
    with connect() as db:
        if request:
            db.execute('UPDATE control_state SET request=NULL WHERE id=1')
        if problems:
            log_action(db, cfg['mode'], target['reason'], [], snapshot(current), error=' '.join(problems))
            return 'Rechazado: ' + ' '.join(problems)
        calibration = st['calibration_started']
        if target['calibrating'] and calibration is None:
            calibration = now
        elif not target['calibrating']:
            calibration = None
        db.execute('UPDATE control_state SET calibration_started=%s WHERE id=1', (calibration,))
        if not commands:
            if cfg['mode'] == 'on' and st['enabled']:
                db.execute('UPDATE control_state SET last_target=%s WHERE id=1', (Jsonb(target),))
            return 'Sin cambios: ' + target['reason']
        if cfg['mode'] == 'dry-run' or not (st['enabled'] or request):
            log_action(db, 'dry-run', target['reason'], commands, snapshot(current))
            return 'Simulación: enviaría ' + ', '.join(commands)
        if commands_today(db) + len(commands) > cfg['max_commands_day']:
            log_action(db, 'on', target['reason'], commands, snapshot(current), error='Límite diario de comandos alcanzado')
            return 'Límite diario de comandos alcanzado.'
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
        if verified:
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
    while stop is None or not stop.is_set():
        if cfg['mode'] in ('dry-run', 'on'):
            try:
                print(step(client, sn, cfg), flush=True)
            except Exception as exc:
                print('Error de control: ' + (str(exc) if isinstance(exc, CloudError) else type(exc).__name__), flush=True)
        # Check for panel requests every minute; full cycle every `interval`.
        for _ in range(max(1, cfg['interval'] // 60)):
            if stop is not None and stop.wait(60):
                return
            if stop is None:
                time.sleep(60)
            with connect() as db:
                if state(db)['request']:
                    break


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Ajustes automáticos de batería vía i.Solar')
    parser.add_argument('--status', action='store_true', help='Solo lee y muestra los ajustes actuales (no envía nada)')
    parser.add_argument('--once', action='store_true', help='Un ciclo con el CONTROL_MODE configurado')
    args = parser.parse_args()
    init()
    client = Cloud(os.environ['SOLAR_USERNAME'], os.environ['SOLAR_PASSWORD'])
    sn = os.environ['SOLAR_DEVICE_SN']
    if args.status:
        params = client.params(sn)
        current = current_settings(params)
        print('Tipo de batería (BT):', current['battery_type'], '· umbrales por SOC:', current['soc_mode'])
        for name, key in KEYS.items():
            print(f'  {key:5s} {name:10s} {params.get(key)!r}')
        print('Parámetros informados por el equipo:', ', '.join(sorted(params)))
        return
    if args.once:
        print(step(client, sn))
        return
    run()


if __name__ == '__main__':
    main()
