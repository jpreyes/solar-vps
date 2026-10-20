"""Local-only connection UI. Credentials live in process memory, never on disk.

Start with DB_* configured and a loopback-only database. This file is not used
by Docker/Gunicorn. The test panel binds exclusively to 127.0.0.1.
"""
import os
import hmac
import secrets
import threading
from flask import jsonify, request, Response, session, redirect
from app import app, protected
from cloud import Cloud, CloudError
from storage import init, save, event
from scheduler import run_collector
from weather import run_weather

lock = threading.Lock()
connected = False
os.environ.setdefault('DASHBOARD_USER', 'admin')
os.environ.setdefault('DASHBOARD_PASSWORD', 'solar-local')
os.environ['LOCAL_SERIAL_DB'] = '1'
os.environ.setdefault('HISTORY_SYNC_SECONDS','60')
app.config.update(LOCAL_SESSION_AUTH=True, SECRET_KEY=secrets.token_hex(32),
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')


@app.route('/local/login', methods=['GET', 'POST'])
def local_login():
    error = ''
    if request.method == 'POST':
        if request.headers.get('Origin') != request.host_url.rstrip('/'):
            return Response('Origen no permitido', status=403)
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if (hmac.compare_digest(username.encode(), os.environ['DASHBOARD_USER'].encode())
                and hmac.compare_digest(password.encode(), os.environ['DASHBOARD_PASSWORD'].encode())):
            session.clear()
            session['local_authorized'] = True
            return redirect('/local')
        error = '<p role="alert">Usuario o contraseña local incorrectos.</p>'
    return Response('''<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ingreso local · Solar</title>
<link rel="stylesheet" href="/static/style.css"></head><body>
<header><div class="brand">☀ <b>SOLAR</b></div><span class="tag">PRUEBA LOCAL</span></header>
<main><section class="panel"><p class="eyebrow">ACCESO AL PANEL</p><h1>Ingresa a la prueba local.</h1>
<p class="muted">Este acceso es del panel local. La cuenta de tumcapp.com se introduce en el siguiente paso.</p>
<form method="post" action="/local/login"><div class="filters">
<label>Usuario local<input name="username" required autocomplete="username"></label>
<label>Contraseña local<input name="password" type="password" required autocomplete="current-password"></label>
<button type="submit">Ingresar</button></div></form>''' + error + '''
</section></main></body></html>''', mimetype='text/html', status=401 if error else 200)


def collect(client, sn):
    run_collector(client,sn)


@app.get('/local')
@protected
def setup():
    return Response('''<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Prueba local · Solar</title>
<link rel="stylesheet" href="/static/style.css"><script src="/static/http.js" defer></script><script src="/static/local.js" defer></script></head>
<body><header><div class="brand">☀ <b>SOLAR</b></div><span class="tag">PRUEBA LOCAL</span></header>
<main><section class="panel"><p class="eyebrow">CONECTAR TU EQUIPO</p><h1>Probemos con una lectura real.</h1>
<p>Se consultará directamente <b>https://isolar.tumcapp.com</b>, la API usada por el portal tumcapp.com.</p>
<p class="muted">Las credenciales se usan en memoria y no se escriben en archivos. Las lecturas sí se guardan en la base local. Solo monitoreo.</p>
<form id="connect"><div class="filters"><label>Usuario del portal<input id="username" required autocomplete="username"></label>
<label>Contraseña del portal<input id="password" type="password" required autocomplete="off"></label>
<label>Número de serie<input id="serial" required autocomplete="off"></label>
<button id="submit" type="submit">Conectar y descargar historial</button></div></form>
<p id="result" role="status"></p><p><a href="/">Abrir panel de datos →</a></p>
<p class="small muted">El historial se sincroniza desde el 18 de octubre de 2026. Puedes probar intervalos de 1, 5 o 10 minutos desde el panel. Las lecturas actuales se solicitan cuando visitas el panel. Esta prueba no instala nada en el VPS.</p>
</section></main></body></html>''', mimetype='text/html')


@app.post('/local/connect')
@protected
def connect_device():
    global connected
    if request.headers.get('Origin') != request.host_url.rstrip('/'):
        return jsonify(error='Origen no permitido'), 403
    fields = request.get_json(silent=True) or {}
    username, password, sn = (fields.get(k, '') for k in ('username', 'password', 'serial'))
    if not all(isinstance(v, str) and v and len(v) < 256 for v in (username, password, sn)):
        return jsonify(error='Completa usuario, contraseña y número de serie'), 400
    if not lock.acquire(blocking=False):
        return jsonify(error='Hay una conexión en curso'), 409
    try:
        if connected:
            return jsonify(error='Ya hay una conexión activa. Reinicia el proceso para cambiar de cuenta.'), 409
        client = Cloud(username, password)
        result = client.realtime(sn)
        save(sn, 'realtime', result, {'deviceSn': sn})
        event(True, 'Primera lectura real guardada desde prueba local')
        connected = True
        app.config['LOCAL_LIVE_READER'] = lambda: (sn, client.realtime(sn))
        threading.Thread(target=collect, args=(client, sn), daemon=True).start()
        return jsonify(ok=True)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, CloudError) else type(exc).__name__
        return jsonify(error='No se pudo completar la lectura: ' + detail), 502
    finally:
        lock.release()


if __name__ == '__main__':
    init()
    threading.Thread(target=run_weather,daemon=True).start()
    app.run(host='127.0.0.1', port=8088, debug=False, threaded=True)
