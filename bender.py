from Class.bender import Bender
import sys
param = sys.argv[1]
print("Route Bender 4000")
bender = Bender()
if param == "run":
    bender.run()
else:
    print("run")
