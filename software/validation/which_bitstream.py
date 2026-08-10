#!/usr/bin/env python3
"""
Which bitstream is the board actually running?

WHY THIS WORKS
--------------
FIX 4 added a read-only status register at offset 0x14 whose bit 0 is set when
the delay register (DLY, offset 0x08) has been written as 0 - a setting that is
invalid and is silently clamped to 1.

  * NEW bitstream: write DLY = 0, then 0x14 reads back 1.
  * OLD bitstream: offset 0x14 was not decoded at all, so it always reads 0.

So writing DLY = 0 and reading 0x14 gives a clean one-bit answer.

SAFETY
------
While this runs, the module spends a few microseconds with an invalid delay
setting, so its output is briefly wrong. Run it with the output going to a
scope or signal generator loop - NOT while the feedback loop is connected to
the trap. The original DLY value is written straight back.

REQUIREMENTS
------------
Must run as root, because it maps /dev/mem:

    sudo python3 which_bitstream.py

or paste the code into a notebook started with `sudo jupyter notebook`.

Reads and writes are single 32-bit accesses. Do not replace them with slice
copies - a bulk mmap slice becomes a burst transfer that the bus bridge cannot
acknowledge, which locks the bus and reboots the board.
"""

import os
import mmap
import struct

BASE = 0x40300000      # phase shifter register block (sys[3])
MAP  = 0x1000          # one 4 kB page

DLY  = 0x08            # delay register (read/write)
STAT = 0x14            # status register (read-only, added by FIX 4)

fd  = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
mem = mmap.mmap(fd, MAP, offset=BASE)


def rd(off):
    """Single 32-bit read."""
    return struct.unpack('<I', mem[off:off + 4])[0]


def wr(off, val):
    """Single 32-bit write."""
    mem[off:off + 4] = struct.pack('<I', val & 0xFFFFFFFF)


saved = rd(DLY)        # remember the current delay setting
wr(DLY, 0)             # deliberately write the invalid value
flag = rd(STAT)        # read the clamp status bit
wr(DLY, saved)         # restore immediately

print("DLY before test : %d" % saved)
print("STAT at 0x14    : %d" % flag)
print("DLY restored to : %d" % rd(DLY))
print()

if flag == 1:
    print(">>> NEW bitstream is running.")
    print("    FIX 4, 5 and 6 are present. Latency is L = 3 samples,")
    print("    so the notebook's L_PIPE = 3 is correct.")
elif flag == 0:
    print(">>> OLD bitstream is running.")
    print("    The new one has NOT been loaded onto the board.")
    print("    The notebook says L_PIPE = 3 but the hardware is L = 2, which")
    print("    is why the measured delay came out ~8 ns (one clock) too short.")
else:
    print(">>> Unexpected value - check that BASE is right and that you are root.")

mem.close()
os.close(fd)
