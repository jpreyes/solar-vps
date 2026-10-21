import unittest
from datetime import date
from unittest.mock import Mock, patch
from history_sync import sync_history


class HistorySyncTests(unittest.TestCase):
    @patch('history_sync.mark_history')
    @patch('history_sync.save')
    @patch('history_sync.history_checkpoint', return_value=None)
    def test_first_sync_starts_at_installation(self, checkpoint, save, mark):
        client = Mock()
        client.history.return_value = iter([({'data': {'list': []}}, {})])
        self.assertEqual(sync_history(client, 'TEST', date(2026,10,18), date(2026,10,20)), 1)
        client.history.assert_called_once_with('TEST', '2026-10-18', '2026-10-21')
        mark.assert_called_once_with('TEST', date(2026,10,18), date(2026,10,20), date(2026,10,20))

    @patch('history_sync.mark_history')
    @patch('history_sync.save')
    @patch('history_sync.history_checkpoint', return_value={'start_date':date(2026,10,18),'scanned_through':date(2026,10,21)})
    def test_outage_catches_up_from_durable_checkpoint(self, checkpoint, save, mark):
        client = Mock()
        client.history.return_value = iter([])
        sync_history(client, 'TEST', date(2026,10,18), date(2026,10,29))
        client.history.assert_called_once_with('TEST', '2026-10-19', '2026-10-30')

    @patch('history_sync.mark_history')
    @patch('history_sync.save')
    @patch('history_sync.history_checkpoint', return_value={'start_date':date(2026,10,18),'scanned_through':date(2026,10,29),'reconciled_on':date(2026,10,29)})
    def test_regular_cycle_only_reads_today_after_daily_reconcile(self, checkpoint, save, mark):
        client = Mock()
        client.history.return_value = iter([])
        sync_history(client, 'TEST', date(2026,10,18), date(2026,10,29))
        client.history.assert_called_once_with('TEST', '2026-10-29', '2026-10-30')
        mark.assert_called_once_with('TEST', date(2026,10,18), date(2026,10,29), None)

    @patch('history_sync.mark_history')
    @patch('history_sync.save')
    @patch('history_sync.history_checkpoint', return_value=None)
    def test_failure_does_not_advance_checkpoint(self, checkpoint, save, mark):
        def pages(*args):
            yield {'data': {'list': []}}, {}
            raise RuntimeError('Network failure on second page')
        client = Mock()
        client.history.side_effect = pages
        with self.assertRaises(RuntimeError):
            sync_history(client, 'TEST', date(2026,10,18), date(2026,10,20))
        save.assert_called_once()
        mark.assert_not_called()
