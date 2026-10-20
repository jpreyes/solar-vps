import hashlib
import json
import os
import threading
from contextlib import nullcontext
from datetime import datetime
from zoneinfo import ZoneInfo
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


_local_db_lock = threading.RLock()


class _LocalConnection:
    """PGlite has one backend: hold the lock through the complete transaction."""
    def __init__(self, connection):
        self.connection = connection
        self.released = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self.connection

    def __exit__(self, *args):
        try:
            return self.connection.__exit__(*args)
        finally:
            self.close()

    def close(self):
        try:
            self.connection.close()
        finally:
            if not self.released:
                self.released = True
                _local_db_lock.release()


def connect():
    serial = os.getenv('LOCAL_SERIAL_DB') == '1'
    if serial:
        _local_db_lock.acquire()
    try:
        connection = psycopg.connect(host=os.getenv('DB_HOST', 'localhost'),
                          port=int(os.getenv('DB_PORT', '5432')),
                          dbname=os.getenv('DB_NAME', 'solar'), user=os.getenv('DB_USER', 'solar'),
                          password=os.environ['POSTGRES_PASSWORD'], row_factory=dict_row,
                          connect_timeout=10, **({'prepare_threshold':None} if serial else {}))
        return _LocalConnection(connection) if serial else connection
    except BaseException:
        if serial:
            _local_db_lock.release()
        raise


def init():
    with connect() as db:
        # Safe across web workers and the collector starting together.
        db.execute('SELECT pg_advisory_xact_lock(731893)')
        db.execute('''CREATE TABLE IF NOT EXISTS captures (
          id BIGSERIAL PRIMARY KEY, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          device_sn TEXT NOT NULL, source TEXT NOT NULL, request JSONB NOT NULL,
          response JSONB NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS measurements (
          id BIGSERIAL PRIMARY KEY, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          capture_id BIGINT REFERENCES captures(id), device_sn TEXT NOT NULL,
          source TEXT NOT NULL, device_time_raw TEXT, observed_at TIMESTAMPTZ,
          fingerprint TEXT NOT NULL, payload JSONB NOT NULL,
          UNIQUE(device_sn, source, fingerprint))''')
        db.execute('CREATE INDEX IF NOT EXISTS measurements_time ON measurements(received_at)')
        db.execute('CREATE INDEX IF NOT EXISTS measurements_observed ON measurements((COALESCE(observed_at,received_at)))')
        db.execute('''CREATE TABLE IF NOT EXISTS history_sync (
          device_sn TEXT PRIMARY KEY, start_date DATE NOT NULL, scanned_through DATE NOT NULL,
          checked_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        db.execute('''CREATE TABLE IF NOT EXISTS collection_settings (
          id INTEGER PRIMARY KEY CHECK(id=1), interval_seconds INTEGER NOT NULL,
          last_started TIMESTAMPTZ, last_finished TIMESTAMPTZ, last_duration DOUBLE PRECISION,
          last_pages INTEGER, last_error TEXT)''')
        db.execute('ALTER TABLE collection_settings ADD COLUMN IF NOT EXISTS last_added INTEGER')
        interval=int(os.getenv('HISTORY_SYNC_SECONDS','300'))
        if interval not in (60,300,600,900):
            raise ValueError('HISTORY_SYNC_SECONDS debe ser 60, 300, 600 o 900')
        db.execute('INSERT INTO collection_settings(id,interval_seconds) VALUES (1,%s) ON CONFLICT DO NOTHING',(interval,))
        db.execute('''CREATE TABLE IF NOT EXISTS events (
          id BIGSERIAL PRIMARY KEY, time TIMESTAMPTZ NOT NULL DEFAULT now(),
          ok BOOLEAN NOT NULL, detail TEXT NOT NULL)''')


def device_time(data):
    raw = next((str(data[k]) for k in ('updateTime', 'recordTime', 'createTime', 'T')
                if data.get(k) is not None), None)
    if raw is None:
        return None, None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(os.getenv('DEVICE_TIMEZONE', 'America/Santiago')))
        return raw, parsed
    except (ValueError, TypeError):
        return raw, None


def save(sn, source, response, request, db=None):
    rows = [response['data']] if source == 'realtime' else response['data']['list']
    with (nullcontext(db) if db is not None else connect()) as db:
        capture = db.execute('''INSERT INTO captures(device_sn, source, request, response)
          VALUES (%s,%s,%s,%s) RETURNING id''',
          (sn, source, Jsonb(request), Jsonb(response))).fetchone()['id']
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw, observed = device_time(row)
            digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            db.execute('''INSERT INTO measurements(capture_id,device_sn,source,device_time_raw,observed_at,fingerprint,payload)
              VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
              (capture, sn, source, raw, observed, digest, Jsonb(row)))


def history_checkpoint(sn):
    with connect() as db:
        return db.execute('SELECT * FROM history_sync WHERE device_sn=%s', (sn,)).fetchone()


def mark_history(sn, start, through):
    with connect() as db:
        db.execute('''INSERT INTO history_sync(device_sn,start_date,scanned_through)
          VALUES (%s,%s,%s) ON CONFLICT(device_sn) DO UPDATE
          SET start_date=excluded.start_date,scanned_through=excluded.scanned_through,checked_at=now()''',
          (sn, start, through))


def event(ok, detail):
    with connect() as db:
        db.execute('INSERT INTO events(ok,detail) VALUES (%s,%s)', (ok, detail))
