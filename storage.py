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
                          connect_timeout=10, options='-c TimeZone=UTC',
                          **({'prepare_threshold':None} if serial else {}))
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
        # Identical vendor pages are re-read every cycle: keep one row per distinct
        # response and count repeats, instead of a full JSON copy every 5 minutes.
        db.execute('ALTER TABLE captures ADD COLUMN IF NOT EXISTS response_hash TEXT')
        db.execute('ALTER TABLE captures ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ')
        db.execute('ALTER TABLE captures ADD COLUMN IF NOT EXISTS seen_count INTEGER NOT NULL DEFAULT 1')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS captures_distinct ON captures(device_sn,source,response_hash)')
        db.execute('CREATE INDEX IF NOT EXISTS measurements_time ON measurements(received_at)')
        db.execute('CREATE INDEX IF NOT EXISTS measurements_source_time ON measurements(source,device_sn,observed_at)')
        db.execute('CREATE INDEX IF NOT EXISTS measurements_observed ON measurements((COALESCE(observed_at,received_at)))')
        db.execute('''CREATE TABLE IF NOT EXISTS history_sync (
          device_sn TEXT PRIMARY KEY, start_date DATE NOT NULL, scanned_through DATE NOT NULL,
          checked_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        db.execute('ALTER TABLE history_sync ADD COLUMN IF NOT EXISTS reconciled_on DATE')
        db.execute('''CREATE TABLE IF NOT EXISTS collection_settings (
          id INTEGER PRIMARY KEY CHECK(id=1), interval_seconds INTEGER NOT NULL,
          last_started TIMESTAMPTZ, last_finished TIMESTAMPTZ, last_duration DOUBLE PRECISION,
          last_pages INTEGER, last_error TEXT)''')
        db.execute('ALTER TABLE collection_settings ADD COLUMN IF NOT EXISTS last_added INTEGER')
        interval=int(os.getenv('HISTORY_SYNC_SECONDS','300'))
        if interval not in (60,300,600,900):
            raise ValueError('HISTORY_SYNC_SECONDS debe ser 60, 300, 600 o 900')
        db.execute('INSERT INTO collection_settings(id,interval_seconds) VALUES (1,%s) ON CONFLICT DO NOTHING',(interval,))
        db.execute('''CREATE TABLE IF NOT EXISTS weather_forecast (
          location TEXT NOT NULL, valid_at TIMESTAMPTZ NOT NULL, fetched_at TIMESTAMPTZ NOT NULL,
          payload JSONB NOT NULL, PRIMARY KEY(location,valid_at))''')
        db.execute('''CREATE TABLE IF NOT EXISTS climate_hourly (
          location TEXT NOT NULL, observed_at TIMESTAMPTZ NOT NULL, ghi REAL, gti REAL,
          temperature REAL, cloud_cover REAL, PRIMARY KEY(location,observed_at))''')
        db.execute('ALTER TABLE climate_hourly ADD COLUMN IF NOT EXISTS gti_planes REAL[]')
        db.execute('CREATE TABLE IF NOT EXISTS climate_meta (location TEXT PRIMARY KEY, planes JSONB NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS control_state (
          id INTEGER PRIMARY KEY CHECK(id=1), enabled BOOLEAN NOT NULL DEFAULT false,
          paused_reason TEXT, request JSONB, last_target JSONB, last_params JSONB,
          params_at TIMESTAMPTZ, calibration_started TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        db.execute('INSERT INTO control_state(id) VALUES (1) ON CONFLICT DO NOTHING')
        db.execute('''CREATE TABLE IF NOT EXISTS control_actions (
          id BIGSERIAL PRIMARY KEY, time TIMESTAMPTZ NOT NULL DEFAULT now(), mode TEXT NOT NULL,
          reason TEXT NOT NULL, commands JSONB NOT NULL, before JSONB, response_code TEXT,
          verified BOOLEAN, after JSONB, error TEXT)''')
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


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def store_capture(db, sn, source, request, response):
    """Insert a capture or, if this exact response was already archived, count the repeat."""
    return db.execute('''INSERT INTO captures(device_sn, source, request, response, response_hash, last_seen_at)
      VALUES (%s,%s,%s,%s,%s,now())
      ON CONFLICT(device_sn,source,response_hash) DO UPDATE
      SET last_seen_at=now(), seen_count=captures.seen_count+1 RETURNING id''',
      (sn, source, Jsonb(request), Jsonb(response), digest(response))).fetchone()['id']


def save(sn, source, response, request, db=None):
    rows = [response['data']] if source == 'realtime' else response['data']['list']
    with (nullcontext(db) if db is not None else connect()) as db:
        capture = store_capture(db, sn, source, request, response)
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw, observed = device_time(row)
            db.execute('''INSERT INTO measurements(capture_id,device_sn,source,device_time_raw,observed_at,fingerprint,payload)
              VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
              (capture, sn, source, raw, observed, digest(row), Jsonb(row)))


def history_checkpoint(sn):
    with connect() as db:
        return db.execute('SELECT * FROM history_sync WHERE device_sn=%s', (sn,)).fetchone()


def mark_history(sn, start, through, reconciled_on=None):
    with connect() as db:
        db.execute('''INSERT INTO history_sync(device_sn,start_date,scanned_through,reconciled_on)
          VALUES (%s,%s,%s,%s) ON CONFLICT(device_sn) DO UPDATE
          SET start_date=excluded.start_date,scanned_through=excluded.scanned_through,checked_at=now(),
              reconciled_on=COALESCE(excluded.reconciled_on,history_sync.reconciled_on)''',
          (sn, start, through, reconciled_on))


def event(ok, detail):
    with connect() as db:
        db.execute('INSERT INTO events(ok,detail) VALUES (%s,%s)', (ok, detail))
