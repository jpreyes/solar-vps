import unittest
from datetime import datetime,timezone
from weather import rows_from_response, VARIABLES


class WeatherTests(unittest.TestCase):
    def test_showers_requested_separately_and_preserved(self):
        self.assertIn('showers', VARIABLES)
        self.assertIn('precipitation', VARIABLES)
        response = {'hourly_units': {'showers':'mm','precipitation':'mm'},
                    'hourly': {'time':['2026-10-20T12:00'], 'showers':[0.4], 'precipitation':[1.2]}}
        row = next(rows_from_response(response, datetime(2026,10,20,13,tzinfo=timezone.utc)))
        self.assertEqual(row[2]['showers'], 0.4)
        self.assertEqual(row[2]['precipitation'], 1.2)
        self.assertEqual(row[2]['units']['showers'], 'mm')

    def test_only_past_hourly_values_are_archived_with_units_and_source(self):
        response={'latitude':-39.8,'longitude':-73.2,'hourly_units':{'shortwave_radiation':'W/m²'},
                  'hourly':{'time':['2026-10-20T12:00','2026-10-20T13:00'],
                            'shortwave_radiation':[250,300],'temperature_2m':[None,15]}}
        rows=list(rows_from_response(response,datetime(2026,10,20,12,30,tzinfo=timezone.utc)))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][1].tzinfo,timezone.utc)
        self.assertEqual(rows[0][2]['shortwave_radiation'],250)
        self.assertIsNone(rows[0][2]['temperature_2m'])
        self.assertEqual(rows[0][2]['units']['shortwave_radiation'],'W/m²')
        self.assertEqual(rows[0][2]['data_kind'],'weather_model_hourly')

    def test_incomplete_weather_arrays_do_not_silently_import(self):
        with self.assertRaises(ValueError):
            list(rows_from_response({'hourly':{'time':['2026-10-20T12:00'],'temperature_2m':[]}}))

    def test_missing_hourly_series_rejected(self):
        with self.assertRaises(ValueError):list(rows_from_response({}))
