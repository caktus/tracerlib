import sys

def f():
    return sys._getframe()

class A(object):
    def m1(self):
        return sys._getframe()
    def m2(self, x, y):
        pass
