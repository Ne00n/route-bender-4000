#!/usr/bin/python3
from Class.bender import Bender
import sys, os
path = os.path.dirname(os.path.realpath(__file__))
print("Route Bender 4000")
if len(sys.argv) == 1:
    bender = Bender(path)
    bender.run()
elif sys.argv[1] == "level":
    bender = Bender(path,True,sys.argv[2])
    bender.run()
elif sys.argv[1] == "deamon":
    bender = Bender(path,True)
    bender.deamon()
elif sys.argv[1] == "clear":
    bender = Bender(path,False)
    bender.clear()
elif sys.argv[1] == "show":
    bender = Bender(path,False)
    bender.show()
elif sys.argv[1] == "stats":
    bender = Bender(path)
    bender.stats()
elif sys.argv[1] == "optimize":
    bender = Bender(path)
    bender.optimize(sys.argv[2],sys.argv[3])
elif sys.argv[1] == "debug":
    bender = Bender(path,True,"debug")
    bender.debug(sys.argv[2],sys.argv[3])
else:
    print("deamon, show, clear, debug, optimize, level, stats")
