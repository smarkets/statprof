from mock import patch

from statprof import stop


def test_stop_fails_if_profiling_isnt_running():
    with patch('statprof.state', profile_level=0):
        try:
            stop()
        except Exception:
            pass
        else:
            raise Exception('Call above should have failed')
