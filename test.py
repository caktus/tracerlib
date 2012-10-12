from __future__ import print_function

import sys
import unittest
import collections

import mock

import tracerlib

import testmod


def foobar(x, *args, **kwargs):
    return sys._getframe()


class FrameInspectorTestCase(unittest.TestCase):

    def setUp(self):
        self.inspector = tracerlib.FrameInspector(foobar(1, 2, a='b'))

    def test_name(self):
        self.assertEqual('foobar', self.inspector.func_name)

    def test_args(self):
        self.assertEqual((1, 2), self.inspector.args)

    def test_kwargs(self):
        self.assertEqual({'a': 'b'}, self.inspector.kwargs)

    def test_named_positional(self):
        inspector = tracerlib.FrameInspector(foobar(x=1))
        self.assertEqual({}, inspector.kwargs)

    def test_all_arg_values(self):
        args = self.inspector.all_arg_values()

        self.assertEqual(args['x'], 1)
        self.assertEqual(args['*args'], (2,))
        self.assertEqual(args['**kwargs'], {'a': 'b'})

    def test_global_func_qual_name(self):
        q = tracerlib.FrameInspector(testmod.f()).qual_name
        self.assertEqual('testmod.f', q)

    def test_class_method_qual_name(self):
        q = tracerlib.FrameInspector(testmod.A().m1()).qual_name
        self.assertEqual('testmod.A.m1', q)

Record = collections.namedtuple('Record', ['event', 'func_name'])

class TracerManagerTestCase(unittest.TestCase):

    def setUp(self):
        sys.settrace(None)
        self.tm = tracerlib.TracerManager()
        self.tm.add(self.record)
        self.records = []

    def record(self, frame, event, arg):
        func_name = tracerlib.FrameInspector(frame).func_name
        self.records.append(Record(event, func_name))

    def get_record(self, event, i):
        j = -1
        for rec in self.records:
            if rec.event == event:
                j += 1
            if j == i:
                return rec
        raise IndexError("Event %r:%d not in %r" % (event, i, self.records))

    def test_start_and_stop(self):
        assert None is sys.gettrace()
        self.tm.start()
        self.assertIn(self.tm, tracerlib._active_managers)
        self.assertEqual(tracerlib._global_tracer, sys.gettrace())
        self.tm.stop()
        assert None is sys.gettrace()

    def test_context_manager(self):
        assert None is sys.gettrace()
        with self.tm:
            self.assertIn(self.tm, tracerlib._active_managers)
            self.assertEqual(tracerlib._global_tracer, sys.gettrace())
        assert None is sys.gettrace()

    def test_multiple_managers(self):
        tm = self.tm
        tm2 = tracerlib.TracerManager()
        with tm:
            with tm2:
                self.assertEqual(2, len(tracerlib._active_managers))
                self.assertIn(tm, tracerlib._active_managers)
                self.assertIn(tm2, tracerlib._active_managers)
                self.assertEqual(tracerlib._global_tracer, sys.gettrace())
            self.assertEqual(1, len(tracerlib._active_managers))
            self.assertEqual(tracerlib._global_tracer, sys.gettrace())
        self.assertEqual(0, len(tracerlib._active_managers))
        self.assertEqual(None, sys.gettrace())

    def test_trace(self):
        def f():
            pass
        def g():
            f()
        with self.tm:
            f()
            g()
        # ending the with implies an extra two records
        self.assertEqual('f', self.get_record('call', 0).func_name)
        self.assertEqual('g', self.get_record('call', 1).func_name)
        self.assertEqual('f', self.get_record('call', 2).func_name)


class TracerTestCase(unittest.TestCase):

    def setUp(self):
        self.tm = tracerlib.TracerManager()
        self.mock = mock.Mock()
        self.tracer = tracerlib.Tracer(self.mock)
        self.tm.add(self.tracer)

    def test_watch_match(self):
        self.tracer.watch("no_mod")
        with self.tm:
            testmod.f()
        self.assertEqual(0, self.mock.call_count)

        self.tracer.unwatch("no_mod")
        self.tracer.watch("testmod.f")
        with self.tm:
            testmod.f()
        self.assertNotEqual(0, self.mock.call_count)

    def test_watch_match_wildcard(self):
        self.tracer.watch("testmod.A.*")
        with self.tm:
            testmod.f()
        self.assertEqual(0, self.mock.call_count)

        self.mock.reset_mock()

        a = testmod.A()
        with self.tm:
            a.m1()
        self.assertNotEqual(0, self.mock.call_count)

    def test_watch_not(self):
        self.tracer.watch("-testmod.A.*")
        with self.tm:
            testmod.f()
        self.assertNotEqual(0, self.mock.call_count)

        self.mock.reset_mock()

        a = testmod.A()
        with self.tm:
            a.m1()
        self.assertEqual(0, self.mock.call_count)

    def test_watch_line(self):
        self.tracer.events = ['line']
        self.tracer.watch('line:5')
        with self.tm:
            testmod.l(True)
        self.assertNotEqual(0, self.mock.call_count)

        self.mock.reset_mock()

        with self.tm:
            testmod.l(False)
        self.assertEqual(0, self.mock.call_count)

    def test_watch_expression(self):
        self.tracer.events = ['line']
        self.tracer.watch('testmod.v')
        self.tracer.watch('true:a==2')

        with self.tm:
            testmod.v()

        self.assertEqual(1, self.mock.call_count)
        self.mock.assert_called_with('v', args=(), kwargs={}, lineno=12)

    def test_incall(self):
        self.tracer.watch('testmod.a')

        with self.tm:
            self.assertFalse(self.tracer.incall)
            def test():
                self.assertTrue(self.tracer.incall)
            with mock.patch('testmod.b', test):
                testmod.a()

    def test_child_tracer(self):
        t = mock.Mock()
        self.tracer.watch('testmod.a')
        child = tracerlib.Tracer(t, ['call'], ['testmod.b'], parent=self.tracer)
        self.tm.add(child)

        self.assertEqual(0, t.call_count, 'Tracer called before even enabling!')
        with self.tm:
            self.assertEqual(0, t.call_count, 'Tracer called before calling function!')
            testmod.b()
            self.assertEqual(0, t.call_count, 'Tracer called when parent was not in-call!')

        with self.tm:
            testmod.a()
            self.assertEqual(1, t.call_count)


ONE_BLOCK = """
foo:1
bar:2
"""
TWO_BLOCK = """
one

two
"""
ONE_CHILD = """
parent
    child
"""
TWO_CHILD = """
parent
    child1
    child1

    child2
    child2
"""
UNNESTING = """
top1
    nest1
top2
    nest2
"""

class ConfigLoaderTestCase(unittest.TestCase):
    def setUp(self):
        self.loader = tracerlib.ConfigLoader()

    def test_parse_one_block(self):
        data = self.loader._parse(ONE_BLOCK)

        self.assertEqual(1, len(data), data)
        rules, children = data[0]
        self.assertEqual(2, len(rules), rules)
        #self.assertEqual(0, len(children), data[0])

    def test_parse_one_child(self):
        data = self.loader._parse(ONE_CHILD)

        self.assertEqual(1, len(data), data)
        rules, children = data[0]
        self.assertEqual(['parent'], rules)
        child_rules, child_children = children[0]
        self.assertEqual(['child'], child_rules)
        self.assertEqual(0, len(child_children))

    def test_parse_multi_blocks(self):
        data = self.loader._parse(TWO_BLOCK)

        self.assertEqual(2, len(data), data)
        self.assertEqual(["one"], data[0][0])
        self.assertEqual(["two"], data[1][0])

    def test_parse_multi_child(self):
        data = self.loader._parse(TWO_CHILD)

        self.assertEqual(1, len(data), data)
        rules, children = data[0]
        self.assertEqual(['parent'], rules)
        self.assertEqual((['child1', 'child1'], []), children[0])
        self.assertEqual((['child2', 'child2'], []), children[1])

    def test_parse_unnesting(self):
        data = self.loader._parse(UNNESTING)

        self.assertEqual(2, len(data), data)

        rules, children = data[0]
        self.assertEqual(['top1'], rules)
        crules, cchildren = children[0]
        self.assertEqual(['nest1'], crules)

        rules, children = data[1]
        self.assertEqual(['top2'], rules)
        crules, cchildren = children[0]
        self.assertEqual(['nest2'], crules)

    def test_tracers(self):
        tm = self.loader.loads(UNNESTING)

        self.assertEqual(4, len(tm.tracers))
        self.assertIs(tm.tracers[0], tm.tracers[1].parent)
        self.assertIs(tm.tracers[2], tm.tracers[3].parent)


if __name__ == '__main__':
    unittest.main()
