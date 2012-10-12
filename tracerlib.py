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

import sys, os
import re
import inspect
import collections
import traceback


_global_tracer_manager = None
_global_env_tracer = False
_active_managers = []

def _protected_trace_func(func):
    def _(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            traceback.print_exc()
            return None
    return _

def _global_tracer(frame, event, arg):
    # Can be None during termination
    if _active_managers:
        for tm in _active_managers:
            f = _protected_trace_func(tm._trace)
            f(frame, event, arg)
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

    def __init__(self, *tracers):
        self.tracers = list(tracers)

    def add(self, tracer):
        """Add a tracer function to be managed."""

        self.tracers.append(tracer)

    def remove(self, tracer):
        """Remove a tracer function."""

        for i, t in enumerate(self.tracers):
            if t is tracer:
                del self.tracers[i]
                break

    def _trace(self, frame, event, arg):
        drop = []
        for i, tracer in enumerate(self.tracers):
            try:
                tracer(frame, event, arg)
            except BaseException as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                print("Failed tracer %r" % (tracer,), file=sys.stderr)
                traceback.print_exc()
                #drop.append(i)
        drop.reverse()
        for i in drop:
            del self.tracers[i]

    def start(self):
        """Begin tracing with all the tracers registered."""

        if self not in _active_managers:
            _active_managers.append(self)

        # We don't need to trace our own exit
        for tracer in self.tracers:
            if hasattr(tracer, 'watch'):
                tracer.watch("-match:tracerlib.TracerManager.__exit__")
                tracer.watch("-match:tracerlib.TracerManager.stop")

        _start_tracing()
    __enter__ = start 

    def stop(self):
        """Stop all the tracers registered with this manager."""

        _active_managers.remove(self)
        if not _active_managers:
            _stop_tracing()

        # We don't need to trace our own exit
        for tracer in self.tracers:
            if hasattr(tracer, 'unwatch'):
                tracer.unwatch("-match:tracerlib.TracerManager.__exit__")
                tracer.unwatch("-match:tracerlib.TracerManager.stop")

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
            return getattr(module, self.func_name).func_code == self.frame.f_code
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
        module = sys.modules.get(self.module)
        lineno = self.frame.f_code.co_firstlineno
        if module:
            source = inspect.getsourcelines(module)[0]
            class_name = None
            def get_indent():
                return len(source[lineno - 1]) - len(source[lineno - 1].lstrip(' \t'))
            indent = get_indent()
            # Walk backwards through the source from the current line, looking
            # for the previous class statement. Assume we're "in" that class.
            while class_name is None and lineno >= 0:
                if source[lineno - 1].startswith('class '):
                    class_name = source[lineno - 1].split('class ', 1)[1].rstrip(':\n').split('(')[0]
                    break
                lineno -= 1
            else:
                class_name = '<unknown class>'
        else:
            module = '<unknown module>'
            class_name = '<unknown class>'

        return '%s.%s.%s' % (self.module, class_name, self.func_name)

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

    def __init__(self, func=None, events=None, watch=None, parent=None):
        self.events = events
        self._trace = func
        self._watch = []
        self.parent = parent
        self.incall = 0
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

    def check_event(self, frame, event, arg):
        lineno = frame.f_lineno
        successes = []
        self.frame_insp = fi = FrameInspector(frame)
        func_name = fi.func_name

        # If we have a parent, only proceed if the parent is in-call
        if self.parent is not None:
            if not self.parent.incall:
                return False

        if self.events is None or event in self.events:
            arginfo = fi.all_arg_values()

            qn_parts = fi.qual_name.split('.')
            for watch in self._watch:
                orig_watch = watch
                failed = False
                negate = watch[0] == '-'
                watch = watch[1 if negate else 0:]
                try:
                    rule_type, watch = watch.split(':', 1)
                except ValueError:
                    rule_type = 'match'
                if rule_type == 'match':
                    if watch.endswith('.*'):
                        failed = not fi.qual_name.startswith(watch[:-2])
                    elif watch != fi.qual_name:
                        failed = True
                elif rule_type == 'line' and event == 'line':
                    failed = lineno != int(watch)
                elif rule_type == 'true':
                    try:
                        #print('EVAL', repr(watch), 'IN', frame.f_locals)
                        failed = not eval(watch, frame.f_globals, frame.f_locals)
                    except Exception, e:
                        #print('TRACERLIB CONDITION ERROR:', e.__class__.__name__, e)
                        failed = True

                if negate:
                    failed = not failed

                #if fi.qual_name.startswith('testmod'):
                #    print(rule_type, ('-' if negate else '+') + watch, fi.qual_name, 'failed' if failed else 'passed')

                if not failed:
                    successes.append(orig_watch)

        return len(successes) == len(self._watch)

    def __call__(self, frame, event, arg):
        if self.check_event(frame, event, arg):
            fi = self.frame_insp
            func_name = fi.func_name
            lineno = frame.f_lineno

            # Track incall status
            if event == 'call':
                self.incall += 1
            elif event == 'exception':
                self.incall -= 1
            elif event == 'return':
                self.incall -= 1

            # Call registered trace function
            if self._trace is not None:
                self._trace(func_name, args=fi.args, kwargs=fi.kwargs, lineno=lineno)
            elif event == 'exception':
                self.trace_exception(func_name, fi.args, fi.kwargs, arg)
            elif event == 'line':
                self.trace_line(func_name, lineno)
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
                if '\n' in s:
                    s = s.split('\n', 1)[0] + ' ...'
                p.append(s)
            else:
                try:
                    r = repr(s)
                except Exception:
                    r = object.__repr__(s)
                if '\n' in r:
                    r = r.split('\n', 1)[0] + ' ...'
                p.append(r)

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
        self.report_call(inspector.qual_name, args, kwargs)

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


class ConfigLoader(object):
    """Load a TracerManager and tracers based on a configuration file.

    on:line
    match:mypackage.*
    -  on:call
       match:otherlibrary.somefunction
       log:args
    """
    
    def __init__(self, tracer=Tracer):
        self.tracer = tracer

    def load(self, f):
        data = self._parse(f.read())
        return self._load(data)

    def loads(self, s):
        data = self._parse(s)
        return self._load(data)

    def _load(self, data):
        manager = TracerManager()
        tracers = self._load_tracers(data)
        for t in tracers:
            manager.add(t)
        return manager

    def _load_tracers(self, data, parent=None):
        for (rules, children) in data:
            tracer = self.tracer(watch=rules, parent=parent)
            yield tracer
            for child in self._load_tracers(children, parent=tracer):
                yield child

    def _parse(self, s):
        data = []
        # Format of the data is a series of (rules, children) tuples
        # rules is a list of strings
        # children is a nested form of the same structure

        state = {
            'cur_data': data,
            'data_stack': [data],
            'cur_rules': None,      # The current rules being read
            'cur_children': None,   # The current block's children
            'indent': 0,
            'indent_levels': [],
        }

        def cur_data():
            return state['cur_data']

        def add_rule(rule):
            if rule:
                if state['cur_rules'] is None:
                    state['cur_rules'] = []
                    state['cur_children'] = []
                state['cur_rules'].append(rule)

        def clear_current():
            state['cur_rules'] = None
            state['cur_children'] = None

        def add_tracer():
            if state['cur_rules']:
                cur_data().append((state['cur_rules'], state['cur_children']))
            clear_current()

        def start_nest():
            add_tracer()
            state['cur_data'] = cur_data()[-1][1]
            state['data_stack'].append(state['cur_data'])

        def end_nest():
            done_data = state['data_stack'].pop()
            state['cur_data'] = state['data_stack'][-1]
            return done_data

        def indent(i=None):
            if i:
                state['indent_levels'].append(i)
                state['indent'] += i
            return state['indent']

        def unindent():
            add_tracer()
            if state['indent_levels']:
                state['indent'] -= state['indent_levels'][-1]
                state['indent_levels'].pop()
            return indent()


        lines = s.split('\n')
        # START
        for line in lines:
            if line.strip() and line[:indent()].strip(' '):
                # UNNEST
                # Return to previous indentation
                unindent()
                # Stop processing the last block and start a new one
                # cur_data's parent should now be the rules and children
                end_nest()

            line = line[indent():]
            line_indent = len(line) - len(line.lstrip(' '))
            if line_indent:
                # NEST - Now adding children to the last block
                # Add the current block, and make its children current
                line = line[line_indent:]
                indent(line_indent)
                start_nest()
            if not line.strip():
                # TERM - End this block of rules, start a new tracer at the same level
                add_tracer()
            add_rule(line)

        add_tracer()

        return data


_pth = """import sys,tracerlib;tracerlib.addtracer(tracerlib.StackTracer(sys.stderr)) if not tracerlib._global_env_tracer else None;tracerlib._global_env_tracer=True"""
def main(args):
    this_env = sys.path[-1]
    if os.path.split(this_env)[-1] == 'site-packages':
        pth_path = os.path.join(this_env, 'tracerlib.pth')
        if args:
            cmd = args[-1]
            if cmd == 'off':
                os.unlink(pth_path)
            elif cmd == 'on':
                with open(pth_path, 'w') as f:
                    f.write(_pth)
            else:
                print("Tracerlib commands:")
                print()
                print("on: Enable tracing of this virtual environment")
                print("off: Disable tracing of this virtual environment")


if __name__ == '__main__':
    sys.exit(main(sys.argv))
