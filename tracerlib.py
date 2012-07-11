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


_global_tracer_manager = None

def _global_tracer(frame, event, arg):
    for tm in TracerManager._active_managers:
        tm._trace(frame, event, arg)
    return _global_tracer

def _start_tracing():
    sys.settrace(_global_tracer)

def _stop_tracing():
    sys.settrace(None)

def addtracer(tracer):
    """Add a trace function to the global manager."""

    global _global_tracer_manager
    if _global_tracer_manager is None:
        _global_tracer_manager = TracerManager()
    _global_tracer_manager.add(tracer)
    _global_tracer_manager.start()

def removetracer(tracer):
    """Remove a trace function frojm the global manager. Disable tracing if no more tracers are active."""

    global _global_tracer_manager
    if _global_tracer_manager is None:
        _global_tracer_manager = TracerManager()
    _global_tracer_manager.remove(tracer)
    if not _global_tracer_manager.tracers:
        _global_tracer_manager.stop()


class TracerManager(object):
    """Maintains a stack of tracers to enable and disable.

    Can be used as a context manager.

    ::

        with TracerManager(tracer1, tracer2):
            # some
            # code
            # to trace
    """

    _active_managers = []

    def __init__(self, *tracers):
        self.tracers = list(tracers)

    def add(self, tracer, events=None):
        """Add a tracer function to be managed."""

        self.tracers.append((tracer, events))

    def remove(self, tracer):
        """Remove a tracer function."""

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
        """Begin tracing with all the tracers registered."""

        if self not in self._active_managers:
            self._active_managers.append(self)

        # We don't need to trace our own exit
        for (tracer, events) in self.tracers:
            if hasattr(tracer, 'watch'):
                tracer.watch("not:tracerlib.TracerManager.__exit__")
                tracer.watch("not:tracerlib.TracerManager.stop")

        _start_tracing()
    __enter__ = start 

    def stop(self):
        """Stop all the tracers registered with this manager."""

        self._active_managers.remove(self)
        if not self._active_managers:
            _stop_tracing()

        # We don't need to trace our own exit
        for (tracer, events) in self.tracers:
            if hasattr(tracer, 'unwatch'):
                tracer.unwatch("not:tracerlib.TracerManager.__exit__")
                tracer.unwatch("not:tracerlib.TracerManager.stop")

    def __exit__(self, type_, value, tb):
        self.stop()


def print_call(frame, event, arg):
    if event == 'call':
        fi = FrameInspector(frame)
        print(fi.name, fi.args, fi.kwargs)


class FrameInspector(object):
    """Utility class to wrap a frame and introspect it easily."""

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
        """The name of the function called."""

        return self.frame.f_code.co_name

    @property
    def module(self):
        """The name of the module which defines the function."""

        return inspect.getmodulename(self.frame.f_code.co_filename)

    @property
    def is_global(self):
        """If the function is defined module-level."""

        try:
            module = sys.modules[self.module]
        except KeyError:
            module = sys.modules['__main__']

        try:
            return getattr(module, self.func_name).func_code is self.frame.f_code
        except AttributeError:
            return False

    @property
    def qual_name(self):
        """If the function is global or a class method, returns the fully
        qualified name, which can be used to identify the function uniquely.
        """

        if self.is_global:
            return '%s.%s' % (self.module, self.func_name)
        # Try to find a class the function was defined in
        module = sys.modules[self.module]
        lineno = self.frame.f_code.co_firstlineno
        source = inspect.getsourcelines(module)[0]
        class_ = None
        def get_indent():
            return len(source[lineno - 1]) - len(source[lineno - 1].lstrip(' \t'))
        indent = get_indent()
        while class_ is None and lineno >= 0:
            if source[lineno - 1].startswith('class '):
                class_ = getattr(module, source[lineno - 1].split('class ', 1)[1].rstrip(':\n').split('(')[0])
                break
            lineno -= 1
        else:
            raise TypeError("Cannot give qualified name for non-globally accessable function.")

        return '%s.%s.%s' % (self.module, class_.__name__, self.func_name)

    @property
    def args(self):
        """The positional arguments passed to the function."""

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
        """The keyword arguments passed to the function."""

        arginfo = inspect.getargvalues(self.frame)
        L = arginfo.locals
        return L.get(arginfo.keywords, {})


class Tracer(object):
    """Helps handling trace events.

    Can accept a ``func`` argument to use as a standard trace function.
    The tracing can be conditional, based on the ``events`` and ``watch``
    parameters it is created with.

    ``event`` can be one of the trace events, and the tracer will only be used
    when the current event matches one of these. Acceptable events are:

    - call
    - return
    - line
    - exception
    - c_call
    - c_return
    - c_exception

    ``watch`` is a fully qualified name. If given, only functions which match
    will be traced. If ``watch`` is a path to a module, any function or
    method in the module will be traced. If it is a path to a class, only
    methods defined in that class will be traced.

    Rather than passing a function to ``Tracer``, you may subclass it and
    define one or more of the ``trace_*()`` methods, which are invoked
    with event-specific arguments.
    """

    def __init__(self, func=None, events=None, watch=None):
        self.events = None
        self._trace = func
        self._watch = []
        if watch is not None:
            self._watch.extend(watch)

    def watch(self, path):
        """Add an additional watch path to match when tracing.
        
        package.module.functionname
        not:XXX
        """

        self._watch.append(path)

    def unwatch(self, path):
        self._watch.remove(path)

    def __call__(self, frame, event, arg):
        if self.events is None or event in self.events:
            self.frame_insp = fi = FrameInspector(frame)
            func_name = fi.func_name
            arginfo = fi.all_arg_values()

            qn_parts = fi.qual_name.split('.')
            for watch in self._watch:
                try:
                    rule_type, watch = watch.split(':', 1)
                except IndexError:
                    rule_type = 'match'
                if rule_type == 'match':
                    if watch != fi.qual_name:
                        return
                elif rule_type == 'not':
                    if watch == fi.qual_name:
                        return

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
        """Handle a call event. Happens at the start of the called function."""

    def trace_line(self, func_name, line_no):
        """Handle a line event."""

    def trace_return(self, func_name, return_value):
        """Handle a return event. Happens at the end of the returning function."""

    def trace_exception(self, func_name, exctype, value, tb):
        """Handle an exception event."""

    def trace_c_call(self, func_name, c_func):
        pass

    def trace_c_return(self, func_name):
        pass

    def trace_c_exception(self, func_name):
        pass


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


class StackTracer(Tracer):
    """A specialized tracer which watches the entire callstack, and makes it
    easy to respond and log within it. Can be given an ``out`` file to write
    an outline of the entire call graph to.

    If subclassing, you can define a ``frame_tracer`` class to a subclass of
    ``StackFrameTracer`` which is create for each frame of the stack to trace
    within it.
    """

    frame_tracer = StackFrameTracer

    def __init__(self, out=None):
        super(StackTracer, self).__init__()
        self.call_stack = []
        self.out = None

    @property
    def current(self):
        """The last frame on the stack."""
        return self.call_stack[-1]

    @property
    def depth(self):
        """The current depth of the call stack."""
        return len(self.call_stack)

    def report_call(self, func_name, args, kwargs):
        """Logs a call and its arguments."""
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
        cft = self.frame_tracer(func_name, inspector, args, kwargs)
        self.call_stack.append(cft)
        self.report_call(func_name, args, kwargs)

    def trace_line(self, *args, **kwargs):
        self.current.trace_line(*args, **kwargs)

    def trace_return(self, func_name, return_value):
        """Logs the return value at the appropriate level in the graph output."""
        self.current.trace_return(func_name, return_value)
        if self.call_stack:
            print(' ' * (self.depth - 1), 'return ', repr(return_value), sep='', file=self.out)
            self.call_stack.pop()

    def trace_exception(self, *args, **kwargs):
        self.current.trace_exception(*args, **kwargs)
