"""Client derived from the public tumcapp.com web application.

Reads are limited to READ_PATHS. The only write is `send_settings`, restricted
to three whitelisted battery commands (SETTING_COMMAND): SOC back-to-grid,
SOC back-to-battery and charger priority. No device binding, sync, firmware,
output, grid or other settings. Undocumented API: validate with the owner's account.
"""
import hashlib
import random
import time
import requests
import threading
import json
import re
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime

BASE = 'https://isolar.tumcapp.com'
LOGIN = '/api/admin/user/login'
REAL = '/api/admin/realData/getRealByDeviceSn'
HISTORY = '/api/admin/workInfo/getHistoricalData'
PARAM_GET = '/api/admin/paramSet/getParam'
PARAM_SET = '/api/admin/paramSet/setParam'
DEVICES = '/api/admin/deviceUser/getMyDevice'
READ_PATHS = (REAL, HISTORY, PARAM_GET, DEVICES)
# PBCC = back to grid at SOC %, PBDC = back to battery at SOC %, PCP0n = charger priority
# (1 solar first, 2 solar + utility, 3 solar only). Format taken from the portal bundle.
# MNCHGCnnn = total charge current (A), MUCHGCnnn = utility charge current (A); no scaling for prodId 30/subId 105.
SETTING_COMMAND = re.compile(r'(PBCC\d{3}|PBDC\d{3}|PCP0[123]|MNCHGC\d{3}|MUCHGC\d{3})')


class CloudError(Exception):
    def __init__(self,message,retry_after=0,status=None):
        super().__init__(message)
        self.retry_after=retry_after
        self.status=status


def retry_seconds(value):
    try:
        return max(0,float(value))
    except (ValueError,TypeError):
        try:
            return max(0,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
        except (ValueError,TypeError,OverflowError):
            return 0


def signature(payload, key):
    # JS Object.keys insertion order; signature uses values BEFORE form encoding.
    def js_value(v):
        if isinstance(v, bool):
            return 'true' if v else 'false'
        return str(v)
    raw = '&'.join(f'{k}={js_value(v)}' for k, v in payload.items() if v is not None)
    units = raw.encode('utf-16-le', errors='surrogatepass')
    total = sum(int.from_bytes(units[i:i+2], 'little') for i in range(0, len(units), 2))
    digest = hashlib.sha256(str(total).encode()).hexdigest()
    return hashlib.sha256((key + digest[-8:] + digest[:8]).encode()).hexdigest()


class Cloud:
    def __init__(self, username, password, session=None):
        self.username, self.password = username, password
        self.session = session or requests.Session()
        self.token, self.key = '', 'null'
        self.lock = threading.RLock()

    def _post(self, path, payload):
        headers = {'token': self.token, 'vrt': signature(payload, self.key),
                   'utcTime': str(random.random()),
                   'Content-Type': 'application/x-www-form-urlencoded'}
        response = self.session.post(BASE + path, data=payload, headers=headers,
                                     timeout=(10, 45), allow_redirects=False)
        if response.status_code >= 400:
            delay=retry_seconds(response.headers.get('Retry-After'))
            if response.status_code==429:
                delay=max(300,delay)
            raise CloudError(f'HTTP {response.status_code}',retry_after=delay,status=response.status_code)
        if response.status_code != 200:
            raise CloudError('Respuesta HTTP inesperada')
        try:
            result = response.json()
        except ValueError:
            raise CloudError('El servidor no devolvió JSON') from None
        if not isinstance(result, dict) or 'code' not in result:
            raise CloudError('Formato de API desconocido')
        return result

    def login(self):
        password = self.password if self.username.startswith('VCN\\') else hashlib.md5(self.password.encode()).hexdigest()
        self.token, self.key = '', 'null'
        result = self._post(LOGIN, {'userName': self.username, 'password': password})
        if str(result['code']) != '0':
            raise CloudError(f'Inicio de sesión rechazado: código {result["code"]}')
        data = result.get('data') or {}
        if not data.get('token') or not data.get('vrtKey'):
            raise CloudError('Falta token/vrtKey en la respuesta de acceso')
        self.token, self.key = str(data['token']), str(data['vrtKey'])

    def _session_post(self, path, payload):
        """Post with the session token, logging in again once if the cloud says it expired.

        Expiry arrives either as a JSON code or as a bare HTTP 401 (a long-running
        service kept failing for hours on the latter)."""
        if not self.token:
            self.login()
        try:
            result = self._post(path, payload)
        except CloudError as exc:
            if exc.status != 401:
                raise
            result = None
        if result is None or str(result['code']) in ('450', '401', '403'):
            self.login()
            result = self._post(path, payload)
        return result

    def read(self, path, payload):
        with self.lock:
            return self._read(path, payload)

    def _read(self, path, payload):
        if path not in READ_PATHS:
            raise ValueError('Operación no permitida')
        result = self._session_post(path, payload)
        if str(result['code']) != '0':
            raise CloudError(f'Consulta rechazada: código {result["code"]}')
        return result

    def realtime(self, sn):
        result = self.read(REAL, {'deviceSn': sn})
        if not isinstance(result.get('data'), dict) or not result['data']:
            raise CloudError('Lectura vacía o formato desconocido')
        return result

    def params(self, sn):
        """Current settings as reported by the device: {key: 'value min~max' | 'value a,b,c'}."""
        result = self.read(PARAM_GET, {'deviceSn': sn})
        if not isinstance(result.get('data'), dict) or not result['data']:
            raise CloudError('Parámetros vacíos o formato desconocido')
        return result['data']

    def device_status(self, sn):
        """Cloud link of the datalogger: onlineStatus 1/0 as shown by the portal.

        Readings can keep arriving while the live command channel is down; the portal then
        shows the device offline and refuses settings ("设备离线，无法发送命令")."""
        result = self.read(DEVICES, {'pageNum': 1, 'pageSize': 200})
        rows = (result.get('data') or {}).get('list') or []
        row = next((r for r in rows if isinstance(r, dict) and str(r.get('deviceSn')) == str(sn)), None)
        if row is None:
            return {'online': None, 'updated': None, 'wifi_version': None, 'firmware': []}
        status = row.get('onlineStatus')
        return {'online': None if status is None else str(status) == '1', 'updated': row.get('modifyTime'),
                'wifi_version': row.get('wfv'), 'firmware': [row.get(k) for k in ('fw', 'fw2', 'fw3', 'fw4') if row.get(k)]}

    def send_settings(self, sn, commands, slots=None):
        """Send up to five whitelisted battery commands. Returns (code, vendor message).

        The message explains non-zero codes (e.g. device offline or no reply); settings
        responses carry no credentials, unlike login, so it is kept (truncated) for the log.
        """
        if not commands or len(commands) > 5 or not all(isinstance(c, str) and SETTING_COMMAND.fullmatch(c) for c in commands):
            raise ValueError('Comando de configuración no permitido')
        slots = slots or [i + 1 for i in range(len(commands))]
        if len(slots) != len(commands) or len(set(slots)) != len(slots) or not all(isinstance(n, int) and 1 <= n <= 9 for n in slots):
            raise ValueError('Claves de comando no válidas')
        payload = {'deviceSn': sn, 'commands': json.dumps({f'S0{n}': c for n, c in zip(slots, commands)},
                                                         separators=(',', ':'))}
        with self.lock:
            result = self._session_post(PARAM_SET, payload)
        message = result.get('message') or result.get('msg') or ''
        return str(result['code']), str(message)[:200]

    def history(self, sn, start, end):
        page = 1
        received = 0
        previous = None
        while True:
            payload = {'deviceSn': sn, 'startDate': start, 'endDate': end,
                       'pageNum': page, 'pageSize': 100}
            result = self.read(HISTORY, payload)
            data = result.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('list'), list):
                raise CloudError('Formato histórico desconocido; importación detenida')
            if not all(isinstance(row, dict) for row in data['list']):
                raise CloudError('Filas históricas desconocidas; importación detenida')
            digest = json.dumps(data['list'], sort_keys=True)
            if data['list'] and digest == previous:
                raise CloudError('La API repitió una página; no se marca el periodo como completo')
            previous = digest
            yield result, payload
            count = len(data['list'])
            received += count
            total = int(data['total']) if data.get('total') is not None else None
            if count == 0 and total is not None and received < total:
                raise CloudError('Historial incompleto: faltan páginas del proveedor')
            if count == 0 or (total is not None and received >= total):
                break
            page += 1
            if page > 10000:
                raise CloudError('Límite de paginación: reduce el rango de fechas')
            time.sleep(1)
