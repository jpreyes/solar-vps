import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from storage import save, history_checkpoint, mark_history

RECONCILE_DAYS = 2


def sync_history(client, sn, start=None, today=None):
    """Monthly batches, durable checkpoints, and a daily reconciliation overlap.

    Regular cycles only re-read today (the provider appends 5-minute rows). Once
    per local day the previous RECONCILE_DAYS are read again to pick up delayed
    publication. A failed batch never advances its checkpoint; saved rows can be
    safely read again.
    """
    initial = start or date.fromisoformat(os.getenv('HISTORY_START_DATE', '2026-10-18'))
    today = today or datetime.now(ZoneInfo(os.getenv('DEVICE_TIMEZONE', 'America/Santiago'))).date()
    if initial > today:
        raise ValueError('HISTORY_START_DATE está en el futuro')
    state = history_checkpoint(sn)
    reconcile = not state or state.get('reconciled_on') != today
    if state and state['start_date'] <= initial:
        overlap = RECONCILE_DAYS if reconcile else 0
        begin = max(initial, min(state['scanned_through'] - timedelta(days=overlap), today - timedelta(days=overlap)))
    else:
        begin = initial
    pages = 0
    while begin <= today:
        end = min(begin + timedelta(days=30), today)
        # Include a one-day boundary overlap whether the provider treats the
        # end date as inclusive or midnight-exclusive. Originals are deduplicated.
        for response, request in client.history(sn, begin.isoformat(), (end + timedelta(days=1)).isoformat()):
            save(sn, 'history', response, request)
            pages += 1
        mark_history(sn, initial, end, today if end == today and reconcile else None)
        begin = end + timedelta(days=1)
        if begin <= today:
            time.sleep(1)
    return pages
