#!/usr/bin/env python

from tracerlib import *

def e(w):
    return w + 2

def f(x):
    if x < 0:
        return e(x)
    return x - 1

def g(y, z):
    y = f(y)
    z = f(z)
    return y + z

tm = TracerManager()
st = StackTracer(sys.stderr)
tm.add(st)

with tm:
    g(-5, 4)
