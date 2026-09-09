import datetime
from unittest.mock import patch
from app.handlers.get_current_time import get_current_time


def test_time():
     fake_now = datetime.datetime(2026, 9, 9, 14, 59, 59)

     with patch('app.handlers.get_current_time.datetime') as mock_datetime:
          mock_datetime.datetime.now.return_value = fake_now

          time_str = get_current_time()
          assert time_str == "14:59"