import unittest
import zipfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET
from excel_export import workbook_file


class ExcelTests(unittest.TestCase):
    def test_entire_archive_long_values_and_formula_safety(self):
        timestamp = datetime(1901, 1, 1, tzinfo=timezone.utc)
        long_value = 'x' * 60001
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {'n': 1}
        climate = MagicMock()
        climate.__iter__.return_value = iter([{'observed_at': timestamp, 'payload': {
            'temperature_2m': 12, 'showers': None, 'precipitation': 0,
            'wind_speed_10m': 5, 'cloud_cover': 25, 'shortwave_radiation': 120}}])
        every_field = MagicMock()
        every_field.__iter__.return_value = iter([{'id': 1, 'observed_at': timestamp,
            'received_at': timestamp, 'device_sn': 'test-only', 'source': 'weather',
            'device_time_raw': '1901-01-01', 'payload': {'long': long_value, 'formula': '=1+1'}}])
        database.cursor.side_effect = lambda name: climate if name == 'excel_climate' else every_field
        climate.__enter__.return_value = climate
        every_field.__enter__.return_value = every_field
        with patch('excel_export.connect') as connection:
            connection.return_value.__enter__.return_value = database
            with workbook_file() as file, zipfile.ZipFile(file) as archive:
                self.assertIsNone(archive.testzip())
                charts = [name for name in archive.namelist() if name.startswith('xl/charts/chart') and name.endswith('.xml')]
                self.assertEqual(len(charts), 6)
                ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                xml = ET.fromstring(archive.read('xl/worksheets/sheet5.xml'))
                rows = xml.findall('m:sheetData/m:row', ns)
                self.assertEqual(len(rows), 5)  # header, 3 string chunks, formula-safe text
                pieces = []
                for row in rows[1:4]:
                    cell = next(c for c in row if c.attrib['r'].startswith('I'))
                    pieces.append(cell.find('m:is/m:t', ns).text)
                self.assertEqual(''.join(pieces), long_value)
                self.assertEqual(xml.findall('.//m:f', ns), [])
                self.assertIn('=1+1', archive.read('xl/worksheets/sheet5.xml').decode())
                sql = every_field.execute.call_args.args[0]
                self.assertNotIn('LIMIT', sql.upper())
                self.assertNotIn('WHERE', sql.upper())
