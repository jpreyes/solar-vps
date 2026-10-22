import unittest
from unittest.mock import Mock, patch
from cloud import Cloud, CloudError, REAL, signature


class CloudTests(unittest.TestCase):
    def session(self, results):
        session = Mock()
        responses = []
        for result in results:
            response = Mock(status_code=200)
            response.json.return_value = result
            responses.append(response)
        session.post.side_effect = responses
        return session

    def test_login_and_read_use_form_with_signed_headers(self):
        session = self.session([{'code': 0, 'data': {'token': 'TEST', 'vrtKey': 'KEY'}},
                                {'code': 0, 'data': {'pvInputPower2': 1360}}])
        client = Cloud('example', 'secret', session)
        self.assertEqual(client.realtime('DEVICE')['data']['pvInputPower2'], 1360)
        call = session.post.call_args
        self.assertEqual(call.args[0], 'https://isolar.tumcapp.com' + REAL)
        self.assertEqual(call.kwargs['data'], {'deviceSn': 'DEVICE'})
        self.assertEqual(call.kwargs['headers']['token'], 'TEST')
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertNotIn('verify', call.kwargs)  # requests retains TLS verification.

    def test_expired_session_renews_and_retries(self):
        session = self.session([{'code': 450}, {'code': 0, 'data': {'token': 'NEW', 'vrtKey': 'KEY'}},
                                {'code': 0, 'data': {'batteryCapacity': 72}}])
        client = Cloud('example', 'secret', session)
        client.token = 'OLD'
        self.assertEqual(client.realtime('DEVICE')['data']['batteryCapacity'], 72)
        self.assertEqual(session.post.call_count, 3)

    def test_http_401_renews_session_and_retries(self):
        expired = Mock(status_code=401, headers={})
        session = self.session([{'code': 0, 'data': {'token': 'NEW', 'vrtKey': 'KEY'}},
                                {'code': 0, 'data': {'batteryCapacity': 72}}])
        session.post.side_effect = [expired, *session.post.side_effect]
        client = Cloud('example', 'secret', session)
        client.token = 'OLD'
        self.assertEqual(client.realtime('DEVICE')['data']['batteryCapacity'], 72)
        self.assertEqual(session.post.call_args.kwargs['headers']['token'], 'NEW')

    def test_settings_retry_once_after_http_401(self):
        expired = Mock(status_code=401, headers={})
        session = self.session([{'code': 0, 'data': {'token': 'NEW', 'vrtKey': 'KEY'}}, {'code': 0}])
        session.post.side_effect = [expired, *session.post.side_effect]
        client = Cloud('example', 'secret', session)
        client.token = 'OLD'
        self.assertEqual(client.send_settings('DEVICE', ['PBCC020']), ('0', ''))
        self.assertEqual(session.post.call_count, 3)

    def test_http_401_after_new_login_is_an_error(self):
        session = self.session([{'code': 0, 'data': {'token': 'NEW', 'vrtKey': 'KEY'}}])
        session.post.side_effect = [Mock(status_code=401, headers={}), *session.post.side_effect,
                                    Mock(status_code=401, headers={})]
        client = Cloud('example', 'secret', session)
        client.token = 'OLD'
        with self.assertRaises(CloudError) as error:
            client.realtime('DEVICE')
        self.assertEqual(error.exception.status, 401)
        self.assertEqual(session.post.call_count, 3)

    def test_other_http_errors_do_not_log_in_again(self):
        session = Mock()
        session.post.return_value = Mock(status_code=500, headers={})
        client = Cloud('example', 'secret', session)
        client.token = 'OLD'
        with self.assertRaises(CloudError):
            client.realtime('DEVICE')
        self.assertEqual(session.post.call_count, 1)

    def test_history_paginates_until_total(self):
        session = self.session([{'code': 0, 'data': {'list': [{'x': 1}] * 100, 'total': 101}},
                                {'code': 0, 'data': {'list': [{'x': 2}], 'total': 101}}])
        client = Cloud('example', 'secret', session)
        client.token = 'TOKEN'
        with patch('cloud.time.sleep'):
            pages = list(client.history('DEVICE', '2026-10-19', '2026-10-20'))
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[-1][1]['pageNum'], 2)

    def test_vendor_failure_does_not_echo_sensitive_messages(self):
        session = self.session([{'code': 599002, 'message': 'SECRET VALUE'}])
        with self.assertRaises(CloudError) as error:
            Cloud('example', 'secret', session).login()
        self.assertNotIn('SECRET', str(error.exception))

    def test_empty_data_is_not_a_measurement(self):
        client = Cloud('', '', self.session([{'code': 0, 'data': None}]))
        client.token = 'TOKEN'
        with self.assertRaises(CloudError):
            client.realtime('DEVICE')

    def test_mutation_is_rejected(self):
        client = Cloud('', '', Mock())
        with self.assertRaises(ValueError):
            client.read('/api/admin/paramSet/setParam', {})
        client.session.post.assert_not_called()

    def test_history_respects_actual_page_sizes(self):
        client = Cloud('', '', self.session([
            {'code':0,'data':{'list':[{'id':1}], 'total':2}},
            {'code':0,'data':{'list':[{'id':2}], 'total':2}}]))
        client.token='TEST'
        with patch('cloud.time.sleep'):
            self.assertEqual(len(list(client.history('TEST','2026-10-18','2026-10-20'))),2)

    def test_repeated_history_pages_never_silently_complete(self):
        result={'code':0,'data':{'list':[{'id':1}], 'total':2}}
        client=Cloud('', '', self.session([result,result]))
        client.token='TEST'
        with patch('cloud.time.sleep'), self.assertRaises(CloudError):
            list(client.history('TEST','2026-10-18','2026-10-20'))

    def test_signature_matches_javascript_reference(self):
        # Independent vectors produced with Node's crypto and JS charCodeAt.
        self.assertEqual(signature({'deviceSn': 'DEVICE'}, 'KEY'),
                         '9f2b9059b41825fcd9b9e55e0c7189007aefba192ec43b221d5d1c300ecf5742')
        self.assertEqual(signature({'userName': 'sol☀️😀', 'password': 'abc'}, 'null'),
                         '338d7f7eabfde4951a665e830e05637a2a8b36d6374212be4b06bafafc275e6b')

    def test_rate_limit_honors_retry_after(self):
        session=Mock()
        session.post.return_value=Mock(status_code=429,headers={'Retry-After':'600'})
        with self.assertRaises(CloudError) as error:
            Cloud('','',session)._post(REAL,{})
        self.assertEqual(error.exception.retry_after,600)


if __name__ == '__main__':
    unittest.main()
