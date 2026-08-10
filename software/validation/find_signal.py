#!/usr/bin/env python3
"""
WHERE IS MY SIGNAL?  -  run this on the board, on its own, when a test says
                        "no signal" and you do not believe it.

    sudo python3 find_signal.py

No notebook, no arguments, no settings to get wrong. It sweeps the reference
tone across the whole input range and tells you what is there.

WHY THIS EXISTS
---------------
The measurement window is about 24 kHz wide out of a 62 MHz input range. If the
frequency you typed into a test is wrong, the signal does not come out weak - it
comes out ABSENT, because the decimator removes everything outside the window as
thoroughly as unplugging the cable would.

So "no signal" and "wrong frequency" look identical from inside a test, and no
amount of staring at one test will tell them apart. This looks everywhere
instead, and answers the only two questions that matter:

    is anything reaching the converter at all?
    if so, what frequency is it?

It changes nothing permanently and leaves the chain disabled when it finishes.
"""

import mmap
import os
import struct
import sys
import time

import numpy as np

FS_CLK   = 125e6
ACQ_BASE = 0x40600000

R_CTRL, R_LO_FINC, R_DEC_LOG2, R_SRC_SEL = 0x00, 0x04, 0x08, 0x0C
R_PEEK_I, R_STATUS2, R_BUILD_ID          = 0x18, 0x38, 0x48

#  Gain from the converter to the decimator output, which is what PEEK reports:
#     mixer   x 2^15 / 2 / 2^6 = x 256      (local oscillator, halving, shift)
#     decimator                = x 256      (same at every rate by construction)
CHAIN_GAIN  = 256 * 256
ADC_FS      = 8192.0          # counts for 1 V on the LV setting
NOISE_FLOOR = 2.0e5


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


class Acq(object):
    def __init__(self):
        self.fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        self.m = mmap.mmap(self.fd, 0x1000, offset=ACQ_BASE)

    def w(self, off, val):
        self.m[off:off + 4] = struct.pack('<I', val & 0xFFFFFFFF)

    def r(self, off):
        return struct.unpack('<I', self.m[off:off + 4])[0]

    def tune(self, f_lo, dec_log2, src=0):
        self.w(R_CTRL, 0)
        self.w(R_LO_FINC, int(round(f_lo / FS_CLK * (1 << 32))) & 0xFFFFFFFF)
        self.w(R_DEC_LOG2, dec_log2)
        self.w(R_SRC_SEL, src)
        self.w(R_CTRL, 1 | 32 | 2 | 128)
        self.w(R_CTRL, 1 | 32 | 64)          # correction bypassed: not wanted here

    def level(self, n=400, settle=0.03):
        """Size of whatever is in the window, however fast it is rotating."""
        time.sleep(settle)
        v = np.array([s32(self.r(R_PEEK_I)) for _ in range(n)], dtype=float)
        return float(np.sqrt(v.mean() ** 2 + 2 * v.var()))

    def beat(self, n=600, gap=0.001, settle=0.2):
        """How fast it is going round, from how often it crosses zero."""
        time.sleep(settle)
        v, t0 = [], time.time()
        for _ in range(n):
            v.append(s32(self.r(R_PEEK_I)))
            time.sleep(gap)
        span = time.time() - t0
        v = np.array(v, dtype=float) - np.mean(v)
        return float(np.count_nonzero(np.diff(np.signbit(v))) / (2.0 * span))


def volts(counts):
    return counts / CHAIN_GAIN / ADC_FS


def main():
    if os.geteuid() != 0:
        sys.exit('Run as administrator:   sudo python3 find_signal.py')

    acq = Acq()
    print('=' * 68)
    print(' Looking for a signal on IN1')
    print('=' * 68)

    if acq.r(0x24) == 0xFFFFFFFF:
        sys.exit('The acquisition system is not responding. Is the right bitstream loaded?')
    bid = acq.r(R_BUILD_ID)
    print(' build fingerprint : 0x%08X%s' % (bid, '   (not built by project.ps1 build)'
                                             if bid == 0 else ''))
    print('')

    # --- pass 1: widest window, biggest steps, whole range ------------------
    f_o = FS_CLK / (1 << 6)                      # 1.95 MHz per window at R = 64
    step = 0.25 * f_o
    print(' Sweeping 0.2 - 60 MHz ...')
    freqs = np.arange(0.2e6, 60.0e6, step)
    lv = []
    for i, f in enumerate(freqs):
        acq.tune(f, 6)
        lv.append(acq.level(n=250, settle=0.02))
        if i % 25 == 0:
            sys.stdout.write('   %.0f%%\r' % (100.0 * i / len(freqs)))
            sys.stdout.flush()
    lv = np.array(lv)
    best = freqs[int(np.argmax(lv))]
    print('   done.        ')
    print('')
    print(' strongest at %.3f MHz : %.0f counts' % (best / 1e6, lv.max()))
    print(' quietest             : %.0f counts' % lv.min())

    if lv.max() < NOISE_FLOOR:
        print('')
        print(' NOTHING ANYWHERE.')
        print('')
        print(' The largest thing in the whole 0.2 - 60 MHz range is %.0f counts,' % lv.max())
        print(' which is the noise floor. A connected generator gives millions.')
        print('')
        print(' Check, in this order:')
        print('   1. the generator OUTPUT is switched on - not just the generator')
        print('   2. the cable is in IN1, not IN2 and not OUT1')
        print('   3. the level is a few hundred mV')
        print('   4. the input jumper next to IN1 is on LV')
        print('   5. swap the cable - they fail more often than anything else here')
        acq.w(R_CTRL, 0)
        return 1

    # --- passes 2 and 3: narrow down ---------------------------------------
    for dec, span, n in ((8, 0.8e6, 17), (10, 0.10e6, 21)):
        cand = np.linspace(best - span, best + span, n)
        vals = []
        for f in cand:
            acq.tune(f, dec)
            vals.append(acq.level(n=400, settle=0.05))
        best = cand[int(np.argmax(vals))]
        print(' refined at R = %-5d : %.4f MHz  (%.0f counts)'
              % (1 << dec, best / 1e6, max(vals)))

    # --- last few kilohertz, with the sign ---------------------------------
    f_o = FS_CLK / 1024
    D = 0.10 * f_o
    acq.tune(best, 10);     b0 = acq.beat()
    acq.tune(best - D, 10); b1 = acq.beat()
    if abs((b1 - b0) - D) < 0.35 * D:
        best = best + (b1 - D)

    acq.tune(best, 10)
    amp = acq.level(n=1500)
    acq.w(R_CTRL, 0)

    print('')
    print('=' * 68)
    print(' FOUND IT')
    print('')
    print('   frequency : %.4f MHz' % (best / 1e6))
    print('   amplitude : %.0f counts at the decimator' % amp)
    print('             : about %.0f mV at the input (LV setting)' % (1000 * volts(amp)))
    print('')
    print('   Put this in the setup cell of the test you are running:')
    print('')
    print('       F_SIG = %.0f' % best)
    print('')
    print('=' * 68)
    return 0


if __name__ == '__main__':
    sys.exit(main())
