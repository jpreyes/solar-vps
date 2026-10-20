"""Portable server-side Excel download (Python-only Ubuntu container).

Reads the durable SQL archive, never calls the upstream services. Artifact-tool
is not available in the deployed Python runtime; XlsxWriter is a runtime dependency.
"""
import json
import math
from datetime import timezone
from tempfile import TemporaryFile
import xlsxwriter
from storage import connect
from weather import VARIABLES, weather_id


def workbook_file():
    output = TemporaryFile(suffix='.xlsx')
    try:
        with xlsxwriter.Workbook(output, {'constant_memory': True,
                'strings_to_formulas': False, 'strings_to_urls': False}) as book:
            book.use_zip64()
            header = book.add_format({'bold': True, 'bg_color': '#17354A', 'font_color': '#FFFFFF'})
            date_format = book.add_format({'num_format': 'yyyy-mm-dd hh:mm'})
            info = book.add_worksheet('Información')
            info.set_column(0, 0, 105)
            for i, line in enumerate([
                'Archivo completo · inversor y meteorología de Valdivia',
                'Todas las fechas y variables de SQL; no aplica los filtros del panel.',
                'Datos: todas las mediciones y revisiones, una fila por campo. Valores largos se dividen en partes.',
                'Clima: última revisión de cada hora y ubicación configurada. Fechas UTC.',
                'Open-Meteo: modelo horario, no estación local. https://open-meteo.com/ · CC BY 4.0',
                'Radiación W/m²: promedio de la hora anterior. Precipitación y chubascos: mm por hora.',
                'Gráficos: hasta 30.000 horas distribuidas por todo el periodo. Clima conserva todas las horas.',
                'Respuestas completas del proveedor disponibles en la descarga JSONL.',
            ]):
                info.write(i, 0, line, header if i == 0 else None)
            graphs = book.add_worksheet('Gráficos clima')
            graphs.set_column(0, 15, 12)
            climate = book.add_worksheet('Clima')
            climate.freeze_panes(1, 1)
            climate.set_column(0, 0, 22)
            climate.set_column(1, len(VARIABLES), 24)
            climate.write_row(0, 0, ['Fecha UTC'] + list(VARIABLES), header)
            plot = book.add_worksheet('Series gráficos')
            plot.write_row(0, 0, ['Fecha UTC'] + list(VARIABLES), header)
            plot.set_column(0, 0, 22)
            plot.set_column(1, len(VARIABLES), 24)
            with connect() as db:
                # Consistent snapshot for both sheets during ongoing collection.
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                count = db.execute("SELECT count(DISTINCT observed_at) AS n FROM measurements WHERE source='weather' AND device_sn=%s AND observed_at<=now()", (weather_id(),)).fetchone()['n']
                stride = max(1, math.ceil(count / 30000))
                climate_row = plot_row = 1
                climate_part = 1
                with db.cursor(name='excel_climate') as cursor:
                    cursor.execute("""SELECT DISTINCT ON(observed_at) observed_at,payload FROM measurements
                      WHERE source='weather' AND device_sn=%s AND observed_at<=now()
                      ORDER BY observed_at,id DESC""", (weather_id(),))
                    for index, row in enumerate(cursor):
                        if climate_row == 1048576:
                            climate.autofilter(0, 0, climate_row - 1, len(VARIABLES))
                            climate_part += 1
                            climate = book.add_worksheet('Clima ' + str(climate_part))
                            climate.freeze_panes(1, 1)
                            climate.set_column(0, 0, 22)
                            climate.write_row(0, 0, ['Fecha UTC'] + list(VARIABLES), header)
                            climate_row = 1
                        timestamp = row['observed_at'].astimezone(timezone.utc).replace(tzinfo=None)
                        values = [row['payload'].get(key) for key in VARIABLES]
                        climate.write_datetime(climate_row, 0, timestamp, date_format)
                        climate.write_row(climate_row, 1, values)
                        climate_row += 1
                        if index % stride == 0:
                            plot.write_datetime(plot_row, 0, timestamp, date_format)
                            plot.write_row(plot_row, 1, values)
                            plot_row += 1
                climate.autofilter(0, 0, climate_row - 1, len(VARIABLES))
                part = 0
                sheet = None
                with db.cursor(name='excel_every_field') as cursor:
                    cursor.execute('''SELECT id,received_at,observed_at,device_sn,source,device_time_raw,payload
                      FROM measurements ORDER BY COALESCE(observed_at,received_at),id''')
                    for row in cursor:
                        for key, value in row['payload'].items():
                            if isinstance(value, (dict, list)):
                                value = json.dumps(value, ensure_ascii=False)
                            pieces = [value] if not isinstance(value, str) else [value[i:i+30000] for i in range(0, len(value), 30000)] or ['']
                            for piece_number, piece in enumerate(pieces, 1):
                                if sheet is None or line == 1048576:
                                    if sheet is not None: sheet.autofilter(0, 0, line-1, 8)
                                    part += 1
                                    sheet = book.add_worksheet('Datos ' + str(part))
                                    sheet.freeze_panes(1, 0)
                                    sheet.set_column(0, 8, 24)
                                    sheet.set_column(8, 8, 45)
                                    sheet.write_row(0, 0, ['id', 'received_at UTC', 'observed_at UTC', 'device_sn', 'source', 'device_time_raw', 'field', 'parte', 'value'], header)
                                    line = 1
                                metadata = [row['id'], str(row['received_at']), str(row['observed_at'] or ''), row['device_sn'], row['source'], row['device_time_raw'], key, piece_number, piece]
                                sheet.write_row(line, 0, metadata)
                                line += 1
                if sheet is not None: sheet.autofilter(0, 0, line-1, 8)
            for i, (key, title, unit) in enumerate([
                ('temperature_2m', 'Temperatura', '°C'), ('showers', 'Chubascos', 'mm/hora'),
                ('cloud_cover', 'Nubosidad', '%'), ('precipitation', 'Precipitación total', 'mm/hora'),
                ('wind_speed_10m', 'Viento', 'km/h'), ('shortwave_radiation', 'Irradiancia GHI', 'W/m²'),
            ]):
                if plot_row == 1: continue
                col = VARIABLES.index(key) + 1
                chart = book.add_chart({'type': 'scatter', 'subtype': 'straight'})
                chart.add_series({'name': title, 'categories': ['Series gráficos', 1, 0, plot_row-1, 0],
                                  'values': ['Series gráficos', 1, col, plot_row-1, col],
                                  'line': {'color': '#237C7B', 'width': 1.25}})
                chart.set_title({'name': title})
                chart.set_x_axis({'name': 'Fecha UTC', 'num_format': 'dd/mm hh:mm'})
                chart.set_y_axis({'name': unit})
                chart.set_legend({'none': True})
                chart.show_blanks_as('gap')
                graphs.insert_chart(i//2*16, i%2*8, chart, {'x_scale': 1.1, 'y_scale': 1.05})
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise
