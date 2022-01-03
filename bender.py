#!/usr/bin/python3
from Class.bender import Bender
import sys, os
path = os.path.dirname(os.path.realpath(__file__))
print("Route Bender 4000")
if len(sys.argv) == 1:
    bender = Bender(path)
    bender.run()
elif sys.argv[1] == "clear":
    bender = Bender(path,False)
    bender.clear()
elif sys.argv[1] == "show":
    bender = Bender(path,False)
    bender.show()
elif sys.argv[1] == "debug":
    bender = Bender(path)
    bender.debug()
else:
    print("show, clear, debug")
