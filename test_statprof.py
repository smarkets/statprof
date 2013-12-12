try:
    from cStringIO import StringIO
except ImportError:
    try:
        from StringIO import StringIO
    except ImportError:
        from io import StringIO  # noqa

from os.path import abspath, basename

from mock import Mock
from nose.tools import eq_, ok_

from statprof import CodeKey, display, DisplayFormat, PathFormat, ProfileState, start, stop


def create_frame(filename, lineno, name):
    code = Mock()
    code.co_name = name
    code.co_filename = filename

    frame = Mock()
    frame.f_code = code
    frame.f_lineno = lineno

    return frame


def get_output(**kwargs):
    buffer = StringIO()
    display(buffer, **kwargs)
    buffer.seek(0)
    return buffer.read()


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
    state = ProfileState()
    try:
        state.stop()
    except Exception:
        pass
    else:
        raise Exception('Call above should have failed')


def test_profiling_output_contains_file_names_formatted_appropriately():
    start()

    def fun():
        for i in range(2 ** 20):
            pass

    def fun2():
        for i in range(50):
            fun()

    fun2()
    stop()

    for format in (DisplayFormat.BY_LINE, DisplayFormat.BY_METHOD):
        full_path = abspath(__file__)
        base = basename(__file__)

        content = get_output(format=format, path_format=PathFormat.FULL_PATH)
        assert full_path in content

        content = get_output(format=format, path_format=PathFormat.FILENAME_ONLY)
        assert base in content
        assert full_path not in content
