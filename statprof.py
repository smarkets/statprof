# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

"""
Copyright (C) 2014 Smarkets Limited <support@smarkets.com>
Copyright (C) 2012 Bryan O'Sullivan <bos@serpentine.com>
Copyright (C) 2011 Alex Fraser <alex at phatcore dot com>
Copyright (C) 2004,2005 Andy Wingo <wingo at pobox dot com>
Copyright (C) 2001 Rob Browning <rlb at defaultvalue dot org>

This library is free software; you can redistribute it and/or
modify it under the terms of the GNU Lesser General Public
License as published by the Free Software Foundation; either
version 2.1 of the License, or (at your option) any later version.

This library is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public
License along with this program; if not, contact:

Free Software Foundation           Voice:  +1-617-542-5942
59 Temple Place - Suite 330        Fax:    +1-617-542-2652
Boston, MA  02111-1307,  USA       gnu@gnu.org

statprof is intended to be a fairly simple statistical profiler for
python. It was ported directly from a statistical profiler for guile,
also named statprof, available from guile-lib [0].

[0] http://wingolog.org/software/guile-lib/statprof/

To start profiling, call statprof.start():
>>> start()

Then run whatever it is that you want to profile, for example:
>>> import test.pystone; test.pystone.pystones()

Then stop the profiling and print out the results:
>>> stop()
>>> display()
  %   cumulative      self
 time    seconds   seconds  name
 26.72      1.40      0.37  pystone.py:79:Proc0
 13.79      0.56      0.19  pystone.py:133:Proc1
 13.79      0.19      0.19  pystone.py:208:Proc8
 10.34      0.16      0.14  pystone.py:229:Func2
  6.90      0.10      0.10  pystone.py:45:__init__
  4.31      0.16      0.06  pystone.py:53:copy
    ...

All of the numerical data is statistically approximate. In the
following column descriptions, and in all of statprof, "time" refers
to execution time (both user and system), not wall clock time.

% time
    The percent of the time spent inside the procedure itself (not
    counting children).

cumulative seconds
    The total number of seconds spent in the procedure, including
    children.

self seconds
    The total number of seconds spent in the procedure itself (not
    counting children).

name
    The name of the procedure.

By default statprof keeps the data collected from previous runs. If you
want to clear the collected data, call reset():
>>> reset()

reset() can also be used to change the sampling frequency from the
default of 1000 Hz. For example, to tell statprof to sample 50 times a
second:
>>> reset(50)

This means that statprof will sample the call stack after every 1/50 of
a second of user + system time spent running on behalf of the python
process. When your process is idle (for example, blocking in a read(),
as is the case at the listener), the clock does not advance. For this
reason statprof is not currently not suitable for profiling io-bound
operations.

The profiler uses the hash of the code object itself to identify the
procedures, so it won't confuse different procedures with the same name.
They will show up as two different rows in the output.

Right now the profiler is quite simplistic.  I cannot provide
call-graphs or other higher level information.  What you see in the
table is pretty much all there is. Patches are welcome :-)


Threading
---------

Because signals only get delivered to the main thread in Python,
statprof only profiles the main thread. However because the time
reporting function uses per-process timers, the results can be
significantly off if other threads' work patterns are not similar to the
main thread's work patterns.
"""

import os
import runpy
import signal
import sys

from collections import defaultdict
from contextlib import contextmanager

from six import moves, exec_, iteritems, itervalues


__all__ = ['DisplayFormat', 'start', 'stop', 'reset', 'display', 'profile']


###########################################################################
# Utils

def clock():
    times = os.times()
    return times[0] + times[1]


###########################################################################
# Collection data structures

class ProfileState(object):
    def __init__(self, frequency=None):
        self.profile_level = 0
        self.reset(frequency)

    def is_active(self):
        return self.profile_level > 0

    def reset(self, frequency=None):
        assert self.profile_level == 0, "Can't reset() while statprof is running"
        # total so far
        self.accumulated_time = 0.0
        # start_time when timer is active
        self.last_start_time = None
        # total count of sampler calls
        self.sample_count = 0
        # a float
        if frequency:
            self.sample_interval = 1.0 / frequency
        elif not hasattr(self, 'sample_interval'):
            # default to 1000 Hz
            self.sample_interval = 1.0 / 1000.0
        else:
            # leave the frequency as it was
            pass
        self.remaining_prof_time = None
        # for user start/stop nesting
        self.profile_level = 0
        # whether to catch apply-frame
        self.count_calls = False
        # gc time between start() and stop()
        self.gc_time_taken = 0

    def accumulate_time(self, stop_time):
        self.accumulated_time += stop_time - self.last_start_time

    def start(self):
        state.profile_level += 1

        if state.profile_level == 1:
            self.last_start_time = clock()
            rpt = self.remaining_prof_time
            self.remaining_prof_time = None
            signal.signal(signal.SIGPROF, profile_signal_handler)
            signal.setitimer(signal.ITIMER_PROF, rpt or self.sample_interval, 0.0)
            self.gc_time_taken = 0  # dunno

    def stop(self):
        assert self.profile_level > 0, 'statprof is not running'
        self.profile_level -= 1
        if self.profile_level == 0:
            self.accumulate_time(clock())
            self.last_start_time = None
            rpt = signal.setitimer(signal.ITIMER_PROF, 0.0, 0.0)
            signal.signal(signal.SIGPROF, signal.SIG_IGN)
            self.remaining_prof_time = rpt[0]
            self.gc_time_taken = 0  # dunno


state = ProfileState()


class CodeKey(object):
    cache = {}

    __slots__ = ('filename', 'lineno', 'name')

    def __init__(self, filename, lineno, name):
        self.filename = filename
        self.lineno = lineno
        self.name = name

    @classmethod
    def create_from_frame(cls, frame):
        code = frame.f_code
        return cls(code.co_filename, frame.f_lineno, code.co_name)

    def __eq__(self, other):
        try:
            return (self.lineno == other.lineno and
                    self.filename == other.filename and
                    self.name == other.name)
        except Exception:
            return False

    def __hash__(self):
        return hash((self.lineno, self.filename, self.name))

    def __repr__(self):
        return '%s(%s)' % (
            self.__class__.__name__,
            ', '.join('%r' % getattr(self, k) for k in self.__slots__)
        )

    @classmethod
    def get(cls, frame):
        k = (frame.f_code.co_filename, frame.f_lineno)
        try:
            return cls.cache[k]
        except KeyError:
            v = cls.create_from_frame(frame)
            cls.cache[k] = v
            return v


class CallData(object):
    all_calls = {}

    __slots__ = ('key', 'call_count', 'cum_sample_count', 'self_sample_count')

    def __init__(self, key):
        '''
        :type key: :class:`CodeKey`
        '''
        self.key = key
        self.call_count = 0
        self.cum_sample_count = 0
        self.self_sample_count = 0

    @classmethod
    def get(cls, key):
        try:
            return cls.all_calls[key]
        except KeyError:
            v = CallData(key)
            cls.all_calls[key] = v
            return v


###########################################################################
# SIGPROF handler

def sample_stack_procs(frame):
    state.sample_count += 1
    key = CodeKey.get(frame)
    CallData.get(key).self_sample_count += 1

    keys_seen = set()
    while frame:
        key = CodeKey.get(frame)
        keys_seen.add(key)
        frame = frame.f_back
    for key in keys_seen:
        CallData.get(key).cum_sample_count += 1


def profile_signal_handler(signum, frame):
    if state.profile_level > 0:
        state.accumulate_time(clock())
        sample_stack_procs(frame)
        signal.setitimer(signal.ITIMER_PROF, state.sample_interval, 0.0)
        state.last_start_time = clock()


###########################################################################
# Profiling API

def is_active():
    return state.is_active()


def start():
    '''Install the profiling signal handler, and start profiling.'''
    state.start()


def stop():
    '''Stop profiling, and uninstall the profiling signal handler.'''
    state.stop()


def reset(frequency=None):
    '''Clear out the state of the profiler.  Do not call while the
    profiler is running.

    The optional frequency argument specifies the number of samples to
    collect per second.'''
    state.reset(frequency)
    CallData.all_calls.clear()
    CodeKey.cache.clear()


@contextmanager
def profile():
    start()
    try:
        yield
    finally:
        stop()
        display()


###########################################################################
# Reporting API

class CallStats(object):
    def __init__(self, call_data):
        '''
        :type call_data: :class:`CallData`
        '''
        self_samples = call_data.self_sample_count
        cum_samples = call_data.cum_sample_count
        nsamples = state.sample_count
        secs_per_sample = state.accumulated_time / nsamples

        self.lineno = call_data.key.lineno
        self.filename = call_data.key.filename
        self.function = call_data.key.name
        self.pcnt_time_in_proc = self_samples / nsamples * 100
        self.cum_secs_in_proc = cum_samples * secs_per_sample
        self.self_secs_in_proc = self_samples * secs_per_sample
        self.num_calls = None
        self.self_secs_per_call = None
        self.cum_secs_per_call = None


class DisplayFormat:
    BY_LINE = 0
    BY_METHOD = 1


class PathFormat:
    FULL_PATH = 0
    FILENAME_ONLY = 1
    NO_FORMATTING = 2


def display(fp=None, format=DisplayFormat.BY_LINE, path_format=PathFormat.FULL_PATH):
    '''Print statistics, either to stdout or the given file object.

    :type format: One of :class:`DisplayFormat.BY_*` constants
    :param all_paths_absolute: Print all the file names with full paths.
    '''

    def p(whatever):
        print(whatever, file=fp)

    if fp is None:
        fp = sys.stdout
    if state.sample_count == 0:
        p('No samples recorded.')
        return

    stats = [CallStats(x) for x in itervalues(CallData.all_calls)]

    try:
        path_transformation = {
            PathFormat.FULL_PATH: os.path.abspath,
            PathFormat.FILENAME_ONLY: os.path.basename,
            PathFormat.NO_FORMATTING: lambda path: path
        }[path_format]
    except KeyError:
        raise Exception("Invalid path format")
    else:
        for stat in stats:
            stat.filename = path_transformation(stat.filename)

    try:
        method = {
            DisplayFormat.BY_LINE: display_by_line,
            DisplayFormat.BY_METHOD: display_by_method
        }[format]
    except KeyError:
        raise Exception("Invalid display format")

    method(stats, fp)

    p('---')
    p('Sample count: %d' % state.sample_count)
    p('Total time: %f seconds' % state.accumulated_time)


def display_by_line(stats, fp):
    '''Print the profiler data with each sample line represented
    as one row in a table.  Sorted by self-time per line.'''
    stats.sort(reverse=True, key=lambda x: x.self_secs_in_proc)

    def p(whatever):
        print(whatever, file=fp)

    p('%5.5s %10.10s   %7.7s  %-8.8s' % ('%  ', 'cumulative', 'self', ''))
    p('%5.5s  %9.9s  %8.8s  %-8.8s' % ("time", "seconds", "seconds", "name"))

    for x in stats:
        p('%6.2f %9.2f %9.2f  %s' % (
            x.pcnt_time_in_proc, x.cum_secs_in_proc, x.self_secs_in_proc,
            '%s:%d:%s' % (x.filename, x.lineno, x.function)))


def get_line_source(filename, lineno):
    '''Gets the line text for the line in the file.'''
    lineno -= 1
    fp = None
    try:
        fp = open(filename)
        for i, line in enumerate(fp):
            if i == lineno:
                return line
    except Exception:
        pass
    finally:
        if fp:
            fp.close()

    return ""


def display_by_method(stats, fp):
    '''Print the profiler data with each sample function represented
    as one row in a table.  Important lines within that function are
    output as nested rows.  Sorted by self-time per line.'''

    def p(whatever):
        print(whatever, file=fp)

    p('%5.5s %10.10s   %7.7s  %-8.8s' % ('%  ', 'cumulative', 'self', ''))
    p('%5.5s  %9.9s  %8.8s  %-8.8s' % ("time", "seconds", "seconds", "name"))

    grouped = defaultdict(list)
    for call in stats:
        grouped[call.filename + ":" + call.function].append(call)

    # compute sums for each function
    functiondata = []
    for fname, samples in iteritems(grouped):
        total_cum_sec = 0
        total_self_sec = 0
        total_percent = 0
        for sample in samples:
            total_cum_sec += sample.cum_secs_in_proc
            total_self_sec += sample.self_secs_in_proc
            total_percent += sample.pcnt_time_in_proc
        functiondata.append((fname,
                             total_cum_sec,
                             total_self_sec,
                             total_percent,
                             samples))

    # sort by total self sec
    functiondata.sort(reverse=True, key=lambda x: x[2])

    for function in functiondata:
        p('%6.2f %9.2f %9.2f  %s' % (
            function[3],  # total percent
            function[1],  # total cum sec
            function[2],  # total self sec
            function[0]))  # file:function
        function[4].sort(reverse=True, key=lambda i: i.self_secs_in_proc)
        for call in function[4]:
            # only show line numbers for significant locations ( > 1% time spent)
            if call.pcnt_time_in_proc > 1:
                source = get_line_source(call.filename, call.lineno).strip()
                if len(source) > 25:
                    source = source[:20] + "..."

                p('%33.0f%% %6.2f   line %s: %s' % (
                    call.pcnt_time_in_proc,
                    call.self_secs_in_proc,
                    call.lineno,
                    source))


def main():
    '''Run the given script under the profiler, when invoked as a module
    (python -m statprof ...), and display the profile report once done.
    '''
    if not sys.argv[1:] or sys.argv[1] in ('--help', '-h'):
        print('usage: python -m statprof [-c cmd | -m mod | file] [<args>]')
        sys.exit(2)

    scriptfile = sys.argv[1]

    if scriptfile.startswith("-c"):
        del sys.argv[0]  # Hide 'statprof' from argument list
        if scriptfile == "-c":
            scriptfile = sys.argv[1]
            del sys.argv[1]
        else:
            scriptfile = scriptfile[2:]
            sys.argv[0] = "-c"
        with profile():
            exec_(scriptfile, vars(moves.builtins))

    elif scriptfile.startswith("-m"):
        if scriptfile == "-m":
            scriptfile = sys.argv[2]
            del sys.argv[1:3]
        else:
            scriptfile = scriptfile[2:]
            del sys.argv[1]
        with profile():
            runpy.run_module(scriptfile, run_name="__main__", alter_sys=True)

    else:
        del sys.argv[0]  # Hide 'statprof' from argument list
        with profile():
            runpy.run_path(scriptfile, run_name="__main__")


if __name__ == '__main__':
    import statprof
    statprof.main()
