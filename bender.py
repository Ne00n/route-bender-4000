from Class.bender import Bender
import sys, os
path = os.path.dirname(os.path.realpath(__file__))
print("Route Bender 4000")
bender = Bender(path)
if len(sys.argv) == 1:
    bender.run()
elif sys.argv[1] == "clear":
    bender.clear()
else:
    print("clear")
