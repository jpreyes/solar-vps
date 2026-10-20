import io
import unittest
from unittest.mock import MagicMock,patch
from scheduler import next_delay,run_collector,set_interval


class ScheduleTests(unittest.TestCase):
    def test_one_five_ten_minute_cycles_without_wall_clock_wait(self):
        for interval in (60,300,600):
            with self.subTest(interval=interval):
                clock=[0.0]
                starts=[]
                def sync(*args):
                    starts.append(clock[0])
                    clock[0]+=2
                    return 1
                class Stop:
                    def is_set(self):return False
                    def wait(self,delay):
                        if len(starts)>=2:return True
                        clock[0]+=delay
                        return False
                with patch('scheduler.connect',return_value=MagicMock()),patch('scheduler.settings',return_value={'interval_seconds':interval}),patch('scheduler.sync_history',side_effect=sync),patch('scheduler.time.monotonic',side_effect=lambda:clock[0]),patch('scheduler.event'),patch('sys.stdout',new_callable=io.StringIO):
                    run_collector(object(),'TEST',stop=Stop())
                self.assertEqual(starts,[0.0,float(interval)])

    def test_slow_download_does_not_queue_overlapping_cycles(self):
        self.assertEqual(next_delay(60,100),5)

    def test_retry_after_and_backoff_take_precedence(self):
        self.assertEqual(next_delay(60,2,failures=1,retry_after=600),600)
        self.assertEqual(next_delay(300,2,failures=1),600)

    @patch('scheduler.connect')
    def test_invalid_interval_rejected_before_writing(self,connect):
        for value in (1,30,True,'60',0,120):
            with self.assertRaises(ValueError):set_interval(value)
        connect.assert_not_called()
