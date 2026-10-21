import csv
import hmac
import io
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context, session, redirect, send_file
from storage import connect, init
from cloud import Cloud, CloudError
from storage import save,device_time
import psycopg
import psycopg.types.json
from werkzeug.exceptions import HTTPException
from scheduler import settings, set_interval
from weather import weather_status,weather_id
import analysis
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__, static_folder='static')
if os.getenv('TRUST_PROXY') == '1':
    # Behind an HTTPS reverse proxy the Origin check needs the public scheme/host.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
_local_refresh_lock = threading.Lock()


def protected(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        local_session = app.config.get('LOCAL_SESSION_AUTH', False)
        if local_session and session.get('local_authorized') is True:
            return fn(*args, **kwargs)
        password = os.getenv('DASHBOARD_PASSWORD', '')
        user = os.getenv('DASHBOARD_USER', 'admin')
        auth = request.authorization
        if not password:
            if request.path.startswith('/api/'):
                return jsonify(error='Falta configurar el acceso al panel'), 503
            return Response('Configura DASHBOARD_PASSWORD en el VPS', status=503)
        if not auth or not (hmac.compare_digest(auth.username.encode(), user.encode())
                            and hmac.compare_digest((auth.password or '').encode(), password.encode())):
            if local_session:
                if request.method == 'GET' and not request.path.startswith('/api/'):
                    return redirect('/local/login')
                return jsonify(error='Inicia sesión en /local/login'), 401
            if request.path.startswith('/api/'):
                return jsonify(error='La sesión terminó. Vuelve a ingresar al panel.', login_url='/local/login' if local_session else '/'), 401
            return Response('Acceso requerido', 401, {'WWW-Authenticate': 'Basic realm="Solar VPS"'})
        return fn(*args, **kwargs)
    return wrapped


@app.after_request
def security(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    return response


def period():
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(request.args.get('start', (now - timedelta(days=1)).isoformat()).replace('Z', '+00:00'))
    end = datetime.fromisoformat(request.args.get('end', now.isoformat()).replace('Z', '+00:00'))
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError('Usa fechas ISO con zona horaria y un rango válido')
    return start, end


@app.errorhandler(ValueError)
def invalid(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(psycopg.Error)
def database_error(exc):
    app.logger.error('Database failure: %s', type(exc).__name__)
    if request.path.startswith('/api/'):
        return jsonify(error='La base de datos no está disponible. Reintenta en unos segundos.'), 503
    return Response('La base de datos no está disponible.', status=503)


@app.errorhandler(HTTPException)
def http_error(exc):
    if request.path.startswith('/api/'):
        messages={404:'La ruta solicitada no existe. Recarga el panel para actualizarlo.',
                  405:'El método de la consulta no es válido. Recarga el panel.'}
        return jsonify(error=messages.get(exc.code,'La solicitud no pudo completarse.')), exc.code
    return exc


@app.errorhandler(Exception)
def unexpected_error(exc):
    app.logger.error('Request failure: %s', type(exc).__name__)
    if request.path.startswith('/api/'):
        return jsonify(error='No se pudo completar la consulta. Puedes volver a intentarlo.'), 500
    return Response('No se pudo completar la solicitud.', status=500)


@app.get('/')
@protected
def index():
    return send_from_directory('static', 'index.html')


@app.get('/api/status')
@protected
def status():
    with connect() as db:
        latest = db.execute("SELECT received_at,response FROM captures WHERE source='realtime' ORDER BY id DESC LIMIT 1").fetchone()
        # The 5-minute history is often fresher than the last on-demand reading.
        newest = db.execute('''SELECT received_at,observed_at,payload FROM measurements
          WHERE source IN ('history','realtime') AND observed_at IS NOT NULL
          ORDER BY observed_at DESC,id DESC LIMIT 1''').fetchone()
        last_event = db.execute('SELECT time,ok,detail FROM events ORDER BY id DESC LIMIT 1').fetchone()
        stats = db.execute('SELECT count(*) AS captures,min(received_at) AS since FROM captures').fetchone()
        history = db.execute('SELECT * FROM history_sync ORDER BY checked_at DESC LIMIT 1').fetchone()
        coverage = db.execute("SELECT count(*) AS measurements,min(observed_at) AS first_time,max(observed_at) AS last_time FROM measurements WHERE source='history'").fetchone()
    if latest:
        latest['observed_at']=device_time(latest['response'].get('data',{}))[1]
    if newest and (not latest or not latest['observed_at'] or newest['observed_at']>latest['observed_at']):
        latest={'received_at':newest['received_at'],'observed_at':newest['observed_at'],'response':{'data':newest['payload']}}
    derived=analysis.derive(latest['response'].get('data') or {}) if latest else None
    pv_config={'max_v':analysis.env_float('INVERTER_MAX_PV_V','500'),'panel_voc':analysis.env_float('PV_PANEL_VOC','51.3'),
               'panels':int(analysis.env_float('PV_PANELS_PER_STRING','8')),'mppt_max_v':450,'mppt_min_v':90}
    return jsonify(latest=latest, derived=derived, pv_config=pv_config, event=last_event, stats=stats, history=history, coverage=coverage,collection=settings())


@app.get('/api/field')
@protected
def field_series():
    start,end=period()
    field=request.args.get('field','pvTotal')
    if not field.replace('_','').isalnum() or len(field)>64:
        raise ValueError('Variable no válida')
    return jsonify(analysis.field_series(field,start,end))


@app.get('/api/daily')
@protected
def daily():
    start,end=period()
    zone=analysis.tz()
    # Whole local days so partial first/last days are not under-counted silently.
    start=datetime.combine(start.astimezone(zone).date(),datetime.min.time(),zone)
    with connect() as db:
        rows=analysis.daily_energy(analysis.samples(start,end,db))
        weather=db.execute('''SELECT DISTINCT ON(observed_at) observed_at,payload FROM measurements
          WHERE source='weather' AND device_sn=%s AND observed_at>%s AND observed_at<=%s
          ORDER BY observed_at,id DESC''',(weather_id(),start,end+timedelta(hours=1))).fetchall()
    system,kwps=analysis.system_from_env(),analysis.plane_kwps()
    sun={}
    for w in weather:
        day=(w['observed_at']-timedelta(hours=1)).astimezone(zone).date().isoformat()
        entry=sun.setdefault(day,{'ghi_kwh_m2':0.0,'pv_kwh':0.0,'hours':0})
        entry['ghi_kwh_m2']+=(analysis.num(w['payload'].get('shortwave_radiation')) or 0)/1000
        entry['pv_kwh']+=analysis.pv_kw_from_weather(w['payload'],system,kwps)
        entry['hours']+=1
    for row in rows:
        s=sun.get(row['date'])
        row['ghi_kwh_m2']=round(s['ghi_kwh_m2'],2) if s else None
        row['pv_expected_kwh']=round(s['pv_kwh'],1) if s and s['hours']>=20 else None
    return jsonify(days=rows,basis='kWh integrados de lecturas de 5 min; red solo en modo L (importación real)')


@app.get('/api/insights')
@protected
def insights():
    now=datetime.now(timezone.utc)
    series=analysis.samples(now-timedelta(days=30),now)
    result=analysis.insights(series,now)
    result['thresholds']=analysis.inferred_thresholds(series)
    result['capacity_kwh']=analysis.estimate_capacity_kwh(series)
    nominal=analysis.env_float('BATTERY_KWH','15.36')
    result['capacity_nominal_kwh']=nominal
    if result['capacity_kwh'] and result['capacity_kwh']<0.85*nominal:
        result['alerts'].append({'level':'info','code':'soc_scale','last':None,
          'text':f"El SOC varía como si la batería tuviera {result['capacity_kwh']} kWh, pero la placa dice {nominal} kWh. "
                 'Suele ser un BMS aún sin calibrar (batería nueva) o un sensor de corriente del inversor que mide bajo. '
                 'Una carga completa al 100 % y algunas semanas de datos lo aclaran.'})
    return jsonify(result)


@app.get('/api/strategy')
@protected
def strategy():
    now=datetime.now(timezone.utc)
    series=analysis.samples(now-timedelta(days=400),now)
    # "Current" = what the inverter reports now; fall back to thresholds inferred from mode switches.
    with connect() as db:
        st=db.execute('SELECT last_params FROM control_state WHERE id=1').fetchone()
    p=(st or {}).get('last_params') or {}
    current=({'to_grid_soc':p['to_grid'],'to_battery_soc':p['to_battery']} if p.get('to_grid') is not None and p.get('to_battery') is not None
             else analysis.inferred_thresholds(series))
    study=analysis.strategy_study(series,current)
    return jsonify(study=study,forecast=analysis.forecast())


@app.post('/api/collection/interval')
@protected
def collection_interval():
    if request.headers.get('Origin') != request.host_url.rstrip('/'):
        return jsonify(error='Origen no permitido'),403
    data=request.get_json(silent=True) or {}
    set_interval(data.get('seconds'))
    return jsonify(ok=True,collection=settings())


@app.get('/api/weather')
@protected
def weather_current():
    return jsonify(weather_status())


@app.get('/api/weather/series')
@protected
def weather_series():
    start,end=period()
    with connect() as db:
        rows=db.execute('''SELECT DISTINCT ON(observed_at) observed_at,received_at,payload
          FROM measurements WHERE source='weather' AND device_sn=%s
          AND observed_at>=%s AND observed_at<%s ORDER BY observed_at,id DESC LIMIT 5001''',
          (weather_id(),start,end)).fetchall()
    return jsonify(rows=rows[:5000],truncated=len(rows)>5000,time_basis='hourly_weather_model_UTC')


@app.post('/api/refresh')
@protected
def refresh():
    if request.headers.get('Origin') != request.host_url.rstrip('/'):
        return jsonify(error='Origen no permitido'), 403
    if os.getenv('LOCAL_SERIAL_DB') == '1':
        # The embedded test database has one backend. Release it before any
        # vendor HTTP call so history and status remain available while waiting.
        if not _local_refresh_lock.acquire(blocking=False):
            return jsonify(cached=True, busy=True), 202
        try:
            with connect() as db:
                recent = _recent_reading(db)
            if recent:
                return jsonify(cached=True)
            return _capture_current()
        finally:
            _local_refresh_lock.release()
    # Cross-worker throttle: an open page may request one new snapshot per minute.
    with connect() as db:
        if not db.execute('SELECT pg_try_advisory_xact_lock(731894) AS locked').fetchone()['locked']:
            return jsonify(cached=True, busy=True), 202
        if _recent_reading(db):
            return jsonify(cached=True)
        return _capture_current(db)


def _recent_reading(db):
    return db.execute("SELECT id FROM captures WHERE source='realtime' AND received_at > now()-interval '60 seconds' LIMIT 1").fetchone()


def _capture_current(db=None):
    callback = app.config.get('LOCAL_LIVE_READER')
    try:
        if callback:
            sn, result = callback()
        else:
            if not all(os.getenv(k) for k in ('SOLAR_USERNAME','SOLAR_PASSWORD','SOLAR_DEVICE_SN')):
                return jsonify(error='Conecta primero el equipo en /local'), 409
            sn = os.environ['SOLAR_DEVICE_SN']
            client = Cloud(os.environ['SOLAR_USERNAME'], os.environ['SOLAR_PASSWORD'])
            result = client.realtime(sn)
        save(sn, 'realtime', result, {'deviceSn': sn}, db=db)
    except psycopg.Error:
        raise
    except Exception as exc:
        detail = str(exc) if isinstance(exc, CloudError) else type(exc).__name__
        return jsonify(error='No se pudo consultar al proveedor: '+detail), 502
    return jsonify(ok=True)


@app.get('/api/series')
@protected
def series():
    start, end = period()
    with connect() as db:
        rows = db.execute('''WITH ordered AS (
          SELECT DISTINCT ON (device_sn,COALESCE(observed_at,received_at))
          received_at,COALESCE(observed_at,received_at) AS observed_at,device_time_raw,source,payload
          FROM measurements WHERE source IN ('realtime','history') AND COALESCE(observed_at,received_at) >= %s
          AND COALESCE(observed_at,received_at) < %s
          ORDER BY device_sn,COALESCE(observed_at,received_at),(source='history') DESC,id DESC)
          SELECT * FROM ordered ORDER BY observed_at LIMIT 5001''', (start, end)).fetchall()
    return jsonify(rows=rows[:5000], truncated=len(rows) > 5000,
                   time_basis='observed_at: fecha de la medición; recepción si falta una fecha interpretable')


@app.get('/api/strategy/estimate')
@protected
def strategy_estimate():
    def pct(name, default=None):
        value=request.args.get(name,default)
        if value is None:
            return None
        if not value.isdigit() or int(value)%5 or not 5<=int(value)<=100:
            raise ValueError('Umbrales en múltiplos de 5 entre 5 y 100')
        return int(value)
    low,high=pct('low','20'),pct('high','30')
    wlow,whigh=pct('winter_low'),pct('winter_high')
    if high<low+5 or (wlow is not None and (whigh is None or whigh<wlow+5)):
        raise ValueError('La vuelta a batería debe superar la vuelta a red en al menos 5 puntos')
    result=analysis.estimate_thresholds(low,high,(wlow,whigh) if wlow is not None else None)
    if result is None:
        return jsonify(error='La climatología aún se está descargando'),503
    return jsonify(result)


@app.post('/api/control/rules')
@protected
def control_rules():
    if not _same_origin():
        return jsonify(error='Origen no permitido'),403
    import control
    cfg=control.config()
    data=request.get_json(silent=True) or {}
    rules={}
    if 'base' in data:
        low,high=(data['base']+[None,None])[:2] if isinstance(data['base'],list) else (None,None)
        if not all(type(v) is int for v in (low,high)) or low%5 or high%5 or not cfg['min_soc']<=low<=60 or not low+5<=high<=100:
            raise ValueError(f'Umbrales: vuelta a red {cfg["min_soc"]}–60 %, vuelta a batería ≥ red + 5, múltiplos de 5')
        rules['base']=[low,high]
    for key in ('winter','storm','enabled'):
        if key in data:
            if not isinstance(data[key],bool):
                raise ValueError(f'{key} debe ser verdadero o falso')
            rules[key]=data[key]
    with connect() as db:
        current=db.execute('SELECT rules FROM control_state WHERE id=1').fetchone()['rules'] or {}
        enabled=rules.pop('enabled',None)
        merged={**current,**rules}
        db.execute('UPDATE control_state SET rules=%s,updated_at=now() WHERE id=1',(psycopg.types.json.Jsonb(merged),))
        if enabled is not None:
            if enabled and cfg['mode']!='on':
                return jsonify(error='Para activar la automatización, el VPS debe tener CONTROL_MODE=on.'),409
            db.execute('UPDATE control_state SET enabled=%s,paused_reason=NULL WHERE id=1',(enabled,))
    return jsonify(ok=True,rules=merged)


@app.get('/api/control')
@protected
def control_status():
    import control
    cfg=control.config()
    with connect() as db:
        st=db.execute('SELECT * FROM control_state WHERE id=1').fetchone()
        actions=db.execute('SELECT * FROM control_actions ORDER BY id DESC LIMIT 20').fetchall()
    effective=control.apply_rules(cfg,st.get('rules'))
    return jsonify(mode=cfg['mode'],state=st,actions=actions,charger_labels=control.CHARGER,
                   config={k:(sorted(v) if isinstance(v,set) else v) for k,v in effective.items()},
                   rules=st.get('rules') or {})


def _same_origin():
    return request.headers.get('Origin') == request.host_url.rstrip('/')


@app.post('/api/control/enabled')
@protected
def control_enabled():
    if not _same_origin():
        return jsonify(error='Origen no permitido'),403
    import control
    if control.config()['mode']!='on':
        return jsonify(error='El control está en modo '+control.config()['mode']+'; cambia CONTROL_MODE=on en el VPS para activarlo.'),409
    data=request.get_json(silent=True) or {}
    if data.get('clear_calibration_block') is True:
        # Explicit owner action after an emergency stop of grid charging.
        with connect() as db:
            db.execute('UPDATE control_state SET calibration_blocked=NULL,updated_at=now() WHERE id=1')
        return jsonify(ok=True)
    enabled=data.get('enabled')
    if not isinstance(enabled,bool):
        raise ValueError('Indica enabled true o false')
    with connect() as db:
        db.execute('UPDATE control_state SET enabled=%s,paused_reason=NULL,updated_at=now() WHERE id=1',(enabled,))
    return jsonify(ok=True)


@app.post('/api/control/request')
@protected
def control_request():
    if not _same_origin():
        return jsonify(error='Origen no permitido'),403
    import control
    cfg=control.config()
    if cfg['mode']=='off':
        return jsonify(error='El control está apagado (CONTROL_MODE=off).'),409
    data=request.get_json(silent=True) or {}
    presets={'base':(*cfg['base'],cfg['charger'],'Base'),'winter':(*cfg['winter'],cfg['charger'],'Invierno / reserva')}
    if data.get('preset') in presets:
        low,high,charger,label=presets[data['preset']]
    else:
        low,high,charger,label=data.get('to_grid'),data.get('to_battery'),data.get('charger',cfg['charger']),'Personalizado'
    hours=data.get('hours',24)
    values=(low,high,charger,hours)
    if not all(type(v) is int for v in values):
        raise ValueError('Valores enteros requeridos')
    if low%5 or high%5 or not (cfg['min_soc']<=low<=60) or not (low+5<=high<=100) or charger not in control.CHARGER or not 1<=hours<=336:
        raise ValueError(f'Umbrales fuera de rango: vuelta a red {cfg["min_soc"]}–60 %, vuelta a batería ≥ red + 5, múltiplos de 5; cargador 1–3; 1–336 h.')
    req={'to_grid':low,'to_battery':high,'charger':charger,'hours':hours,'label':f'{label} {low}/{high}',
         'requested_at':datetime.now(timezone.utc).isoformat()}
    with connect() as db:
        db.execute('UPDATE control_state SET request=%s,updated_at=now() WHERE id=1',(psycopg.types.json.Jsonb(req),))
    return jsonify(ok=True,request=req)


@app.get('/api/export.jsonl')
@protected
def export_raw():
    all_data = request.args.get('all') == '1'
    bounds = None if all_data else period()
    with connect() as db:
        db.execute('SELECT 1')  # Report an unavailable DB before starting a file.
    @stream_with_context
    def generate():
        with connect() as db:
            with db.cursor(name='raw_export') as cursor:
                if all_data:
                    cursor.execute('SELECT received_at,device_sn,source,request,response FROM captures ORDER BY id')
                else:
                    cursor.execute('''SELECT received_at,device_sn,source,request,response FROM captures
                      WHERE received_at >= %s AND received_at < %s ORDER BY id''', bounds)
                for row in cursor:
                    yield json.dumps(row, default=str, ensure_ascii=False) + '\n'
    return Response(generate(), mimetype='application/x-ndjson',
                    headers={'Content-Disposition': 'attachment; filename='+('solar-todos-los-originales.jsonl' if all_data else 'solar-originales.jsonl')})


@app.get('/api/export.csv')
@protected
def export_csv():
    all_data = request.args.get('all') == '1'
    bounds = None if all_data else period()
    with connect() as db:
        db.execute('SELECT 1')
    @stream_with_context
    def generate():
        def line(values):
            # Prevent spreadsheet formulas in strings from the upstream service.
            safe = ["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for v in values]
            buf = io.StringIO()
            csv.writer(buf).writerow(safe)
            return buf.getvalue()
        yield '\ufeff' + line(['received_at', 'device_sn', 'source', 'device_time_raw', 'observed_at', 'field', 'value'])
        with connect() as db:
            with db.cursor(name='csv_export') as cursor:
                if all_data:
                    if request.args.get('source')=='weather':
                        cursor.execute('''SELECT received_at,device_sn,source,device_time_raw,observed_at,payload
                          FROM measurements WHERE source='weather' ORDER BY observed_at,id''')
                    else:
                        cursor.execute('''SELECT received_at,device_sn,source,device_time_raw,observed_at,payload
                          FROM measurements ORDER BY COALESCE(observed_at,received_at),id''')
                else:
                    cursor.execute('''SELECT received_at,device_sn,source,device_time_raw,observed_at,payload
                      FROM measurements WHERE COALESCE(observed_at,received_at) >= %s AND COALESCE(observed_at,received_at) < %s ORDER BY COALESCE(observed_at,received_at),id''', bounds)
                for row in cursor:
                    for field, value in row['payload'].items():
                        if isinstance(value, (dict, list)):
                            value = json.dumps(value, ensure_ascii=False)
                        yield line([str(row['received_at']), row['device_sn'], row['source'], row['device_time_raw'],
                                    str(row['observed_at'] or ''), field, value])
    return Response(generate(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename='+('solar-todos-los-datos.csv' if all_data else 'solar-mediciones.csv')})


@app.get('/api/export.xlsx')
@protected
def export_excel():
    from excel_export import workbook_file
    file = workbook_file()
    response = send_file(file, as_attachment=True, download_name='solar-todos-los-datos.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', conditional=False)
    response.call_on_close(file.close)
    return response


if __name__ == '__main__':
    init()
    app.run(host='127.0.0.1', port=8088)
