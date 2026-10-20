"""Independent model-weather archive for Valdivia; no inverter login required."""
import hashlib
import json
import os
import time
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
import requests
from psycopg.types.json import Jsonb
from storage import connect,init

URL='https://api.open-meteo.com/v1/forecast'
VARIABLES=('temperature_2m','relative_humidity_2m','precipitation','rain','showers','weather_code',
           'cloud_cover','wind_speed_10m','wind_direction_10m','surface_pressure',
           'shortwave_radiation','direct_radiation','diffuse_radiation','direct_normal_irradiance')


def location():
    return float(os.getenv('WEATHER_LATITUDE','-39.81422')),float(os.getenv('WEATHER_LONGITUDE','-73.24589'))


def weather_id():
    lat,lon=location()
    return f'weather:Valdivia:{lat}:{lon}'


def rows_from_response(response,now=None):
    now=now or datetime.now(timezone.utc)
    hourly=response.get('hourly',{})
    times=hourly.get('time')
    if not isinstance(times,list):raise ValueError('Falta la serie meteorológica horaria')
    for key,values in hourly.items():
        if not isinstance(values,list) or len(values)!=len(times):
            raise ValueError('Serie meteorológica incompleta')
    for i,raw in enumerate(times):
        observed=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if observed.tzinfo is None:observed=observed.replace(tzinfo=timezone.utc)
        if observed>now:continue  # Never label future forecasts as historical conditions.
        values={key:series[i] for key,series in hourly.items() if key!='time'}
        values.update(weather_source='Open-Meteo',data_kind='weather_model_hourly',
                      latitude=response.get('latitude'),longitude=response.get('longitude'),
                      units=response.get('hourly_units',{}),radiation_basis='preceding_hour_mean_GHI')
        yield raw,observed,values


def sync_weather(session=None):
    lat,lon=location()
    today=datetime.now(ZoneInfo('America/Santiago')).date()
    with connect() as db:
        last=db.execute("SELECT max(received_at) AS time FROM captures WHERE source='weather' AND device_sn=%s",(weather_id(),)).fetchone()['time']
    start=last.date() if last else date.fromisoformat(os.getenv('HISTORY_START_DATE','2026-10-18'))
    params={'latitude':lat,'longitude':lon,'hourly':','.join(VARIABLES),'timezone':'UTC',
            'past_days':min(92,max(3,(today-start).days)),'forecast_days':1,'wind_speed_unit':'kmh'}
    response=(session or requests).get(URL,params=params,timeout=(10,45))
    response.raise_for_status()
    body=response.json()
    if body.get('error'):raise ValueError('El proveedor meteorológico rechazó la consulta')
    rows=list(rows_from_response(body))
    with connect() as db:
        capture=db.execute('''INSERT INTO captures(device_sn,source,request,response)
          VALUES (%s,'weather',%s,%s) RETURNING id''',(weather_id(),Jsonb(params),Jsonb(body))).fetchone()['id']
        for raw,observed,values in rows:
            digest=hashlib.sha256(json.dumps(values,sort_keys=True).encode()+observed.isoformat().encode()).hexdigest()
            db.execute('''INSERT INTO measurements(capture_id,device_sn,source,device_time_raw,observed_at,fingerprint,payload)
              VALUES (%s,%s,'weather',%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
              (capture,weather_id(),raw,observed,digest,Jsonb(values)))
    return len(rows)


def weather_status():
    with connect() as db:
        latest=db.execute("""SELECT received_at,observed_at,payload FROM measurements
          WHERE source='weather' AND device_sn=%s AND observed_at<=now()
          ORDER BY observed_at DESC,id DESC LIMIT 1""",(weather_id(),)).fetchone()
        total=db.execute("SELECT count(DISTINCT observed_at) AS hours FROM measurements WHERE source='weather' AND device_sn=%s",(weather_id(),)).fetchone()['hours']
    return {'city':'Valdivia, Los Ríos','latitude':location()[0],'longitude':location()[1],
            'latest':latest,'hours_archived':total,'source':'Open-Meteo',
            'source_url':'https://open-meteo.com/','kind':'Estimación de modelo horario; no estación local',
            'radiation_basis':'GHI: promedio de la hora anterior, W/m²'}


def run_weather(stop=None):
    while stop is None or not stop.is_set():
        try:print(f'Meteorología guardada: {sync_weather()} horas',flush=True)
        except Exception as exc:print('Error meteorológico: '+type(exc).__name__,flush=True)
        if stop is not None:
            if stop.wait(900):return
        else:time.sleep(900)


if __name__=='__main__':
    init()
    run_weather()
