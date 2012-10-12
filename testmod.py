import sys

def l(c):
    if c:
        pass # LINE 5
    else:
        pass # LINE 7

def v():
    a = 1 # LINE 10
    a = 2 # LINE 11
    a = 3 # LINE 12

def f():
    return sys._getframe()

class A(object):
    def m1(self):
        return sys._getframe()
    def m2(self, x, y):
        pass

