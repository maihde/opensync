#!/usr/bin/env python
import sys
import time
infile = sys.argv[1]
oufile = sys.argv[2]

try:
    rate_hz = int(sys.argv[3])
except IndexError:
    rate_hz = 1

with open(infile) as ff:
    lines = ff.readlines()

with open(oufile, "w") as ff:
    # write the first 3 lines immediately
    for ll in lines[0:3]:
        ff.write(ll)
    # write the remaining lines at specified rate
    for ll in lines[3:]:
        ff.write(ll)
        time.sleep(1.0 / rate_hz)
        ff.flush()
    