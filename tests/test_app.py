import os
import unittest
from unittest.mock import MagicMock, patch
from app import app
import psycopg


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_all_data_routes_require_password(self):
        with patch.dict(os.environ, {'DASHBOARD_PASSWORD': 'test-only'}):
            for path in ('/', '/api/status', '/api/series', '/api/export.csv', '/api/export.jsonl', '/api/export.xlsx'):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_missing_password_fails_closed(self):
        with patch.dict(os.environ, {'DASHBOARD_PASSWORD': ''}):
            self.assertEqual(self.client.get('/').status_code, 503)

    def test_authenticated_page_and_bad_dates(self):
        with patch.dict(os.environ, {'DASHBOARD_PASSWORD': 'test-only', 'DASHBOARD_USER': 'admin'}):
            with self.client.get('/', auth=('admin', 'test-only')) as response:
                self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.get('/api/series?start=bad', auth=('admin', 'test-only')).status_code, 400)
            self.assertEqual(self.client.get('/api/series?start=2026-10-20&end=2026-10-21', auth=('admin', 'test-only')).status_code, 400)

    def test_database_failure_is_json_not_html(self):
        with patch.dict(os.environ, {'DASHBOARD_PASSWORD':'test-only','DASHBOARD_USER':'admin'}), patch('app.connect',side_effect=psycopg.OperationalError('test-only')):
            for path in ('/api/status','/api/series','/api/export.csv?all=1','/api/export.jsonl?all=1'):
                response=self.client.get(path,auth=('admin','test-only'))
                self.assertEqual(response.status_code,503)
                self.assertTrue(response.is_json)
                self.assertIn('base de datos',response.json['error'])

    def test_daily_reports_grid_cost_with_configured_tariff(self):
        rows=[{'date':'2026-10-21','grid_kwh':2.5},{'date':'2026-10-22','grid_kwh':0.0}]
        env={'DASHBOARD_PASSWORD':'test-only','DASHBOARD_USER':'admin','GRID_TARIFF_CLP_KWH':'250'}
        with patch.dict(os.environ,env), patch('app.connect',MagicMock()), patch('app.analysis.samples',return_value=[]), \
                patch('app.analysis.daily_energy',return_value=rows):
            response=self.client.get('/api/daily?start=2026-10-21T00:00:00Z&end=2026-10-22T12:00:00Z',auth=('admin','test-only'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['tariff_clp_kwh'],250)
        self.assertEqual([d['grid_clp'] for d in response.json['days']],[625,0])

    def test_missing_api_route_returns_json(self):
        response=self.client.post('/api/does-not-exist')
        self.assertEqual(response.status_code,404)
        self.assertTrue(response.is_json)

    def test_unexpected_failure_on_demand_is_json(self):
        with patch.dict(os.environ, {'DASHBOARD_PASSWORD':'test-only','DASHBOARD_USER':'admin'}), patch('app.connect',side_effect=RuntimeError('test-only')):
            response=self.client.post('/api/refresh',auth=('admin','test-only'),headers={'Origin':'http://localhost'})
            self.assertEqual(response.status_code,500)
            self.assertTrue(response.is_json)
