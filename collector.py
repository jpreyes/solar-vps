import argparse
import os
from datetime import date
from cloud import Cloud
from storage import init, save, event
from scheduler import run_collector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--history', nargs=2, metavar=('DESDE', 'HASTA'))
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--realtime-once', action='store_true')
    args = parser.parse_args()
    required = ('SOLAR_USERNAME', 'SOLAR_PASSWORD', 'SOLAR_DEVICE_SN', 'POSTGRES_PASSWORD')
    if any(not os.getenv(k) for k in required):
        raise SystemExit('Configura SOLAR_USERNAME, SOLAR_PASSWORD, SOLAR_DEVICE_SN y POSTGRES_PASSWORD en .env')
    init()
    client = Cloud(os.environ['SOLAR_USERNAME'], os.environ['SOLAR_PASSWORD'])
    sn = os.environ['SOLAR_DEVICE_SN']
    if args.realtime_once:
        save(sn, 'realtime', client.realtime(sn), {'deviceSn': sn})
        event(True, 'Lectura actual solicitada manualmente')
        return
    if args.history:
        start, end = map(date.fromisoformat, args.history)
        if start > end:
            raise SystemExit('El inicio debe ser anterior al fin')
        for result, request in client.history(sn, str(start), str(end)):
            save(sn, 'history', result, request)
        event(True, 'Importación histórica terminada')
        return
    if not run_collector(client,sn,once=args.once) and args.once:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
