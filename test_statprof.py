from mock import Mock, patch
from nose.tools import eq_, ok_

from statprof import CodeKey, stop


def create_frame(filename, lineno, name):
    code = Mock()
    code.co_name = name
    code.co_filename = filename

    frame = Mock()
    frame.f_code = code
    frame.f_lineno = lineno

    return frame


def neq(a, b, msg=None):
    if not a != b:
        raise AssertionError(msg or "%r == %r" % (a, b))


def is_(a, b, msg=None):
    if a is not b:
        raise AssertionError(msg or "%r is not %r" % (a, b))


def test_code_key_equitability_and_hashability():
    ck = CodeKey('test.py', 11, 'test')
    eq_(ck, ck)

    ok_(ck in (ck,))
    ok_(ck in [ck])
    ok_(ck in set((ck,)))

    eq_(CodeKey('test.py', 22, 'test'), CodeKey('test.py', 22, 'test'))

    neq(CodeKey('test.py', 22, 'test'), CodeKey('some_other_test.py', 22, 'test'))
    neq(CodeKey('test.py', 22, 'test'), CodeKey('test.py', 123, 'test'))


def test_code_key_create_from_frame_generates_correct_result():
    args = ('/tmp/test.py', 123, 'do_something')
    frame = create_frame(*args)
    code_key = CodeKey.create_from_frame(frame)
    eq_(
        (code_key.filename, code_key.lineno, code_key.name),
        args
    )


def test_code_key_get_method_reuses_instances():
    args = 'main.py', 11, 'main'
    frame = create_frame(*args)
    ck1 = CodeKey.get(frame)
    ck2 = CodeKey.get(frame)

    is_(ck2, ck1)
    eq_(
        (ck1.filename, ck1.lineno, ck1.name),
        args
    )


def test_stop_fails_if_profiling_isnt_running():
    with patch('statprof.state', profile_level=0):
        try:
            stop()
        except Exception:
            pass
        else:
            raise Exception('Call above should have failed')
