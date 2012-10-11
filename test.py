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

if __name__ == '__main__':
    unittest.main()
