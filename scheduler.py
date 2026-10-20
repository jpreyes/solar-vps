import time
from cloud import CloudError
from history_sync import sync_history
from storage import connect, event

ALLOWED_INTERVALS=(60,300,600,900)


def settings():
    with connect() as db:
        return db.execute('SELECT * FROM collection_settings WHERE id=1').fetchone()


def set_interval(seconds):
    if type(seconds) is not int or seconds not in ALLOWED_INTERVALS:
        raise ValueError('Elige 1, 5, 10 o 15 minutos')
    with connect() as db:
        db.execute('UPDATE collection_settings SET interval_seconds=%s WHERE id=1',(seconds,))


def next_delay(interval, elapsed, failures=0, retry_after=0):
    # A single worker runs cycles sequentially: no overlapping queued imports.
    if failures:
        return max(float(retry_after),min(14400,interval*2**min(failures,4)))
    return max(5,interval-elapsed)


def run_collector(client,sn,once=False,stop=None):
    failures=0
    while stop is None or not stop.is_set():
        started=time.monotonic()
        with connect() as db:
            db.execute('UPDATE collection_settings SET last_started=now(),last_error=NULL WHERE id=1')
            before=db.execute("SELECT COALESCE(max(id),0) AS last_id FROM measurements WHERE source='history' AND device_sn=%s",(sn,)).fetchone()['last_id']
        pages=0
        error=None
        retry_after=0
        try:
            pages=sync_history(client,sn)
            failures=0
            event(True,f'Historial sincronizado: {pages} páginas')
            print('Historial sincronizado',flush=True)
        except Exception as exc:
            error=str(exc) if isinstance(exc,CloudError) else type(exc).__name__
            retry_after=getattr(exc,'retry_after',0)
            failures+=1
            event(False,error)
            print('Error de sincronización: '+error,flush=True)
        elapsed=time.monotonic()-started
        with connect() as db:
            added=db.execute("SELECT count(*) AS n FROM measurements WHERE source='history' AND device_sn=%s AND id>%s",(sn,before)).fetchone()['n']
            db.execute('''UPDATE collection_settings SET last_finished=now(),last_duration=%s,
              last_pages=%s,last_error=%s,last_added=%s WHERE id=1''',(elapsed,pages,error,added))
        if once:
            return not failures
        # Read the saved interval during the wait, allowing changes from the UI.
        # Changing the interval never bypasses failure backoff or Retry-After.
        failure_interval=settings()['interval_seconds']
        deadline=time.monotonic()+next_delay(failure_interval,elapsed,failures,retry_after)
        while True:
            now=time.monotonic()
            if not failures:
                interval=settings()['interval_seconds']
                deadline=max(started+interval,started+elapsed+5)
            remaining=deadline-now
            if remaining<=0: break
            if stop is not None:
                if stop.wait(min(5,remaining)):return
            else:
                time.sleep(min(5,remaining))
