#!/usr/bin/env python

# Copyright (c) 2012, Calvin Spealman <ironfroggy@gmail.com>
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# - Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Tracerlib provides a set of helpers to make tracing Python code easier."""

from __future__ import print_function

import sys
import inspect
import collections
import traceback


def _global_tracer(frame, event, arg):
    for tm in TracerManager._active_managers:
        tm._trace(frame, event, arg)
    return _global_tracer

def _start_tracing():
    sys.settrace(_global_tracer)

def _stop_tracing():
    sys.settrace(None)


class TracerManager(object):
    """Maintains a stack of tracers to enable and disable."""

    _active_managers = []

    def __init__(self, *tracers):
        self.tracers = list(tracers)

    def add(self, tracer, events=None):
        self.tracers.append((tracer, events))

    def remove(self, tracer):
        for i, (t, events) in enumerate(self.tracers):
            if t is tracer:
                del self.tracers[i]
                break

    def _trace(self, frame, event, arg):
        drop = []
        for i, (tracer, events) in enumerate(self.tracers):
            if events is None or event in events:
                try:
                    tracer(frame, event, arg)
                except BaseException as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    print("Failed tracer %r" % (tracer,), file=sys.stderr)
                    traceback.print_exc()
                    drop.append(i)
        drop.reverse()
        for i in drop:
            del self.tracers[i]

    def start(self):
        self._active_managers.append(self)
        _start_tracing()
    __enter__ = start 

    def stop(self):
        self._active_managers.remove(self)
        if not self._active_managers:
            _stop_tracing()

    def __exit__(self, type_, value, tb):
        self.stop()


def print_call(frame, event, arg):
    if event == 'call':
        fi = FrameInspector(frame)
        print(fi.name, fi.args, fi.kwargs)


class FrameInspector(object):
    def __init__(self, frame):
        self.frame = frame
        self._arg_values = None
    
    def all_arg_values(self):
        if self._arg_values is None:
            arginfo = inspect.getargvalues(self.frame)
            L = arginfo.locals
            args = collections.OrderedDict()
            for aname in arginfo.args:
                args[aname] = L[aname]
            if arginfo.varargs:
                args['*' + arginfo.varargs] = L[arginfo.varargs]
            if arginfo.keywords:
                args['**' + arginfo.keywords] = L[arginfo.keywords]
            self._arg_values = args
        return self._arg_values

    @property
    def func_name(self):
        return self.frame.f_code.co_name

    @property
    def args(self):
        all_args = self.all_arg_values()
        args = []
        for (k, v) in all_args.items():
            if k.startswith('**'):
                break
            elif k.startswith('*'):
                args.extend(v)
            else:
                args.append(v)
        return tuple(args)

    @property
    def kwargs(self):
        arginfo = inspect.getargvalues(self.frame)
        L = arginfo.locals
        return L.get(arginfo.keywords, {})


class Tracer(object):

    def __init__(self, func=None, events=None):
        self.events = None
        self._trace = func

    def __call__(self, frame, event, arg):
        if self.events is None or event in self.events:
            self.frame_insp = fi = FrameInspector(frame)
            func_name = fi.func_name
            arginfo = fi.all_arg_values()
            if self._trace is not None:
                self._trace(func_name, fi.args, fi.kwargs)
            elif event == 'exception':
                self.trace_exception(func_name, fi.args, fi.kwargs, *args)
            elif event == 'line':
                self.trace_line(func_name, arg)
            elif event == 'return':
                self.trace_return(func_name, arg)
            elif event == 'call':
                self.trace_call(func_name, fi, fi.args, fi.kwargs)
            else:
                getattr(self, 'trace_' + event)(func_name, fi.args, fi.kwargs)
        return self

    def trace_call(self, func_name, inspector, args, kwargs):
        pass

    def trace_line(self, func_name, line_no):
        pass

    def trace_return(self, func_name, return_value):
        pass

    def trace_exception(self, func_name, exctype, value, tb):
        pass

    def trace_c_call(self, func_name, c_func):
        pass

    def trace_c_return(self, func_name):
        pass

    def trace_c_exception(self, func_name):
        pass


class StackTracer(Tracer):

    def __init__(self, out=None):
        super(StackTracer, self).__init__()
        self.call_stack = []
        self.out = None

    @property
    def current(self):
        return self.call_stack[-1]

    @property
    def depth(self):
        return len(self.call_stack)

    def report_call(self, func_name, args, kwargs):
        p = []
        def a(s):
            if isinstance(s, basestring):
                p.append(s)
            else:
                p.append(repr(s))

        a(' ' * (self.depth - 1))
        a(func_name)
        a('(')
        for i, arg in enumerate(args):
            if i > 0:
                a(', ')
            a(arg)
        if args and kwargs:
            a(', ')
        for i, (k, v) in enumerate(kwargs.items()):
            a(k)
            a('=')
            a(v)
        a(')')

        print(''.join(p), file=self.out)

    def trace_call(self, func_name, inspector, args, kwargs):
        cft = StackFrameTracer(func_name, inspector, args, kwargs)
        self.call_stack.append(cft)
        self.report_call(func_name, args, kwargs)

    def trace_line(self, *args, **kwargs):
        self.current.trace_line(*args, **kwargs)

    def trace_return(self, func_name, return_value):
        self.current.trace_return(func_name, return_value)
        if self.call_stack:
            print(' ' * (self.depth - 1), func_name, '() == ', repr(return_value), sep='', file=self.out)
            self.call_stack.pop()

    def trace_exception(self, *args, **kwargs):
        self.current.trace_exception(*args, **kwargs)


class StackFrameTracer(Tracer):

    def __init__(self, func_name, inspector, args, kwargs):
        super(StackFrameTracer, self).__init__()
        self.func_name = func_name
        self.inspector = inspector
        self.args = args
        self.kwargs = kwargs
        self.lineno = None

    def trace_line(self, func_name, lineno):
        self.lineno = lineno

    def trace_return(self, func_name, return_value):
        self.return_value = return_value

    def trace_exception(self, func_name, exctype, value, tb):
        self.exc_info = (exctype, value, tb)
