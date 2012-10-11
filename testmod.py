import sys

def l(c):
    if c:
        pass # LINE 5
    else:
        pass # LINE 7

def f():
    return sys._getframe()

class A(object):
    def m1(self):
        return sys._getframe()
    def m2(self, x, y):
        pass

