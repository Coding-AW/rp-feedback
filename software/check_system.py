#!/usr/bin/env python3
"""
IS EVERYTHING WORKING?  -  run this first, and whenever something seems wrong.

WHAT IT DOES
Asks the board a series of questions and reports the answers in plain English.
It changes nothing that matters and takes about ten seconds.

HOW TO RUN IT
On the Red Pitaya (not on your PC), as administrator:

    sudo python3 check_system.py

It must be run as administrator because it reads the chip's registers directly,
which ordinary users are not allowed to do.

WHAT THE ANSWERS MEAN
Every check prints OK, WARNING or PROBLEM, and anything other than OK is
followed by what to do about it. You do not need to understand the hardware to
act on the result.
"""

import os
import sys
import mmap
import struct
import time

# ---------------------------------------------------------------------------
#  Where things live in the chip. These are fixed addresses, like house numbers.
# ---------------------------------------------------------------------------
PS_BASE  = 0x40300000        # the feedback path (phase shifter)
ACQ_BASE = 0x40600000        # the acquisition system
FS_CLK   = 125e6             # the chip's clock: 125 million ticks per second

PASS, WARN, FAIL = [], [], []


def say(status, title, detail='', advice=''):
    mark = {'OK': '  OK      ', 'WARNING': '  WARNING ', 'PROBLEM': '  PROBLEM '}[status]
    print(mark + title)
    if detail:
        print('            ' + detail)
    if advice:
        for line in advice.split('\n'):
            print('            -> ' + line)
    {'OK': PASS, 'WARNING': WARN, 'PROBLEM': FAIL}[status].append(title)


def heading(text):
    print('')
    print(text)
    print('-' * 60)


class Reg(object):
    """Read and write the chip's registers.

    IMPORTANT: one 32-bit value at a time. Reading a big block in one go sends a
    kind of request the chip's internal bus cannot answer, which locks it up and
    reboots the board. This class only ever does single reads.
    """
    def __init__(self, base):
        self.fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        self.m  = mmap.mmap(self.fd, 0x1000, offset=base)

    def r(self, off):
        return struct.unpack('<I', self.m[off:off + 4])[0]

    def w(self, off, val):
        self.m[off:off + 4] = struct.pack('<I', val & 0xFFFFFFFF)

    def close(self):
        self.m.close()
        os.close(self.fd)


# ===========================================================================
print('=' * 60)
print(' Red Pitaya acquisition system - health check')
print('=' * 60)

# --- 0. are we allowed to look? ---------------------------------------------
if os.geteuid() != 0:
    print('')
    print('  This needs to be run as administrator, because it reads the')
    print('  chip\'s registers directly. Try again with:')
    print('')
    print('      sudo python3 check_system.py')
    print('')
    sys.exit(1)


# ===========================================================================
heading('1. Is the right bitstream loaded?')
# ===========================================================================
#  A bitstream is the file that tells the chip what circuit to be. Loading an
#  old one is the single most common mistake on this project, because the board
#  looks completely healthy afterwards - the light blinks, registers answer -
#  while running last month's design.
#
#  The test: the newer designs have a status register the older ones do not.
#  Writing a deliberately invalid delay setting makes it report the fact.
# ===========================================================================
try:
    ps = Reg(PS_BASE)
    saved = ps.r(0x08)
    ps.w(0x08, 0)
    flag = ps.r(0x14)
    ps.w(0x08, saved)

    acq = Reg(ACQ_BASE)
    acq_alive = (acq.r(0x24) != 0xFFFFFFFF)

    # -----------------------------------------------------------------------
    #  BUILD FINGERPRINT (0x48)
    #
    #  A hash of the Verilog this bitstream was synthesised from, baked in at
    #  build time. It answers a question no file date can:
    #
    #      "Is the logic running on this chip built from the current source?"
    #
    #  A bitstream file can be freshly written, newly dated and byte-different,
    #  and still contain week-old logic - which is exactly what happened on
    #  2026-07-29, when Vivado ran implementation from the previous day's
    #  netlist. It cost an afternoon of re-diagnosing an already-fixed fault.
    #
    #  bitstream_id.txt is written next to the bitstream by project.ps1 build.
    #  Copy it across with the bitstream and this check becomes conclusive.
    # -----------------------------------------------------------------------
    build_id = acq.r(0x48) if acq_alive else 0
    expected = None
    timing_note = None
    for cand in ('bitstream_id.txt',
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'bitstream_id.txt')):
        if os.path.exists(cand):
            # FIX 2026-08-03: this used to be
            #     open(cand).read().strip().upper().replace('0X', '')
            # which takes the WHOLE FILE - fingerprint and all the '#' comment
            # lines below it - and compares that to an 8-character hex string.
            # It could never match, so this check reported "the chip is running
            # DIFFERENT logic" on every single run, including builds that were
            # perfectly current. A check that always cries wolf is worse than no
            # check: it taught us to scroll past the one message that would have
            # caught a stale bitstream.
            #
            # Read the first line that is not blank and not a comment.
            for line in open(cand):
                line = line.strip()
                if line and not line.startswith('#'):
                    expected = line.upper().replace('0X', '')
                    break
            # The timing verdict, if project.ps1 build recorded one. A matching
            # fingerprint proves the board runs what was built; it says nothing
            # about whether what was built works.
            for line in open(cand):
                if 'timing' in line.lower() and 'FAIL' in line:
                    timing_note = line.strip().lstrip('#').strip()
            break

    if acq_alive and build_id == 0:
        say('WARNING', 'This bitstream has no build fingerprint.',
            'Register 0x48 reads zero.',
            'It was not built by project.ps1 build - most likely by pressing\n'
            'Generate Bitstream in Vivado, which does NOT force resynthesis.\n'
            'That can silently produce a new bitstream containing old logic.\n'
            'Rebuild on the PC with:  .\\project.ps1 build')
    elif acq_alive and expected is not None and '%08X' % build_id != expected:
        say('PROBLEM', 'The chip is running DIFFERENT logic from your source.',
            'Chip reports 0x%08X, bitstream_id.txt says 0x%s' % (build_id, expected),
            'Either an old bitstream is loaded, or the build did not pick up\n'
            'your edits. Rebuild with project.ps1 build and reload.')
    elif acq_alive and expected is None:
        # -------------------------------------------------------------------
        #  FIX 2026-08-03. This branch did not exist. When bitstream_id.txt was
        #  absent, `expected` stayed None, the comparison above was skipped, and
        #  control fell through to the plain "OK, build fingerprint 0x..." below
        #  - announcing success for a check that had not been performed.
        #
        #  That is precisely how an afternoon was lost: the fingerprint file was
        #  never written (the build was regenerated from the Vivado GUI, which
        #  does not write it), run_on_board.ps1 skips it silently when missing,
        #  so the board never received it, and this script cheerfully reported
        #  no issues about a bitstream it had not verified. Meanwhile slot 7 was
        #  still a stub, answering every read with zero.
        #
        #  "I could not check" and "I checked and it is fine" must never look
        #  the same.
        # -------------------------------------------------------------------
        say('WARNING', 'The bitstream could NOT be verified - this is not an all-clear.',
            'Chip reports fingerprint 0x%08X, but bitstream_id.txt is not here '
            'to compare it against.' % build_id,
            'That file is written by project.ps1 build next to the bitstream and\n'
            'must be copied to the board with it. Without it, this script cannot\n'
            'tell a current bitstream from a month-old one.\n'
            '  - If you built from the Vivado GUI, the file was never written.\n'
            '    Rebuild with project.ps1 build instead.\n'
            '  - If you built with project.ps1 build, copy bitstream_id.txt\n'
            '    across alongside red_pitaya_top.bit.')
    elif acq_alive and timing_note:
        say('PROBLEM', 'The chip is running a bitstream that FAILED TIMING.',
            'Fingerprint 0x%08X matches - but %s' % (build_id, timing_note),
            'The right logic is loaded, and it is logic that cannot be trusted.\n'
            'A design that misses timing latches half-finished answers: registers\n'
            'read zero, values change when nothing changed, numbers look\n'
            'plausible and are wrong. Fix the timing, rebuild, reload.\n'
            'See CHANGELOG.md for 2026-08-03.')
    elif acq_alive:
        say('OK', 'Build fingerprint 0x%08X.' % build_id)

    if flag == 1 and acq_alive:
        say('OK', 'A recent bitstream is loaded, including the acquisition system.')
    elif flag == 1:
        say('WARNING', 'Feedback path is recent, acquisition system not responding.',
            'Register 0x40600000 is not answering.',
            'The bitstream may predate the acquisition system.\n'
            'Rebuild and reload - see BITSTREAM_WORKFLOW.pdf')
    else:
        say('PROBLEM', 'An OLD bitstream is loaded.',
            'The status register added in July 2026 is not present.',
            'Load the current bitstream. Check the file fingerprint matches,\n'
            'because the board looks healthy either way.\n'
            'See BITSTREAM_WORKFLOW.pdf, Workflow A.')

    # -----------------------------------------------------------------------
    #  WHICH MODULES ARE ACTUALLY IN THIS BITSTREAM  (added 2026-08-03)
    #
    #  A fingerprint tells you whether the chip matches a file on the PC. It
    #  cannot tell you that if the file is missing, and it says nothing at all
    #  about which modules the design contains. This asks each module directly.
    #
    #  The trap this exists for: an unused bus slot is filled by sys_bus_stub,
    #  which drives  bus.ack = 1  and  bus.rdata = 'x  - so it ACKNOWLEDGES the
    #  read and returns zero, instantly and without error. A slot holding a stub
    #  and a slot holding a module whose version register happens to read zero
    #  are indistinguishable from software. On 2026-08-03 Stage 11 read zero
    #  from slot 7, concluded "this bitstream has no sequencer", and was right -
    #  the board was running a build from before the sequencer existed, while
    #  Stages 8 and 9 passed because neither touches slot 7.
    #
    #  Each entry is a module, its version register, and the value it must
    #  return. A version register is the only honest presence test: a stub
    #  cannot fake one.
    # -----------------------------------------------------------------------
    for name, base, off, want in (
            ('parameter sequencer', 0x40700000, 0x0C, 0x5E900001),
    ):
        try:
            got = Reg(base).r(off)
        except Exception as e:
            say('WARNING', 'Could not read the %s at 0x%08X.' % (name, base), str(e))
            continue
        if got == want:
            say('OK', 'The %s is present (version 0x%08X).' % (name, got))
        else:
            say('PROBLEM', 'The %s is NOT in this bitstream.' % name,
                'Slot at 0x%08X answered 0x%08X, expected 0x%08X.'
                % (base, got, want),
                'Zero here does not mean a broken module - it means the slot is\n'
                'still a stub, so this bitstream predates the module. An older\n'
                'build passes every other test on this page and every notebook\n'
                'that does not touch this slot.\n'
                'Rebuild with project.ps1 build, then reload following\n'
                'BITSTREAM_WORKFLOW.pdf Workflow A - the md5sum step in A4 is\n'
                'the one that proves the file actually arrived.')
except Exception as e:
    say('PROBLEM', 'Could not read the chip registers.', str(e),
        'Is this running on the Red Pitaya, as administrator?')
    sys.exit(1)


# ===========================================================================
heading('2. Is the acquisition system alive and sane?')
# ===========================================================================
try:
    # A register that should hold whatever we put in it. If it does not, either
    # the address is wrong or the module is not in the build.
    probe = 0x12345678
    old = acq.r(0x04)
    acq.w(0x04, probe)
    back = acq.r(0x04)
    acq.w(0x04, old)

    if back == probe:
        say('OK', 'Acquisition system is present and its registers respond.')
    else:
        say('PROBLEM', 'Acquisition registers are not holding values.',
            'Wrote 0x%08X, read back 0x%08X' % (probe, back),
            'The module may be missing from the build. Rebuild with\n'
            'project.ps1 build and reload.')
except Exception as e:
    say('PROBLEM', 'Could not talk to the acquisition system.', str(e))


# ===========================================================================
heading('3. Is anything flagged as wrong?')
# ===========================================================================
#  Four warning lights the hardware sets by itself. Each stays lit once it has
#  happened, so a brief fault cannot be missed between two checks.
# ===========================================================================
s2 = acq.r(0x38)
overflow  = bool(s2 & 1)
overrun   = bool(s2 & 2)
bypassed  = bool(s2 & 4)
werr      = bool(s2 & 8)   # STATUS2[3], added 2026-07-30: memory refused a write

if overflow:
    say('PROBLEM', 'Samples were LOST on the way to memory.',
        'The memory could not keep up and some samples were dropped.',
        'This is serious: the record still looks continuous, but time has\n'
        'jumped, so every frequency worked out from it is wrong.\n'
        'Discard any data taken since this was last cleared.')
else:
    say('OK', 'No samples have been lost.')

if overrun:
    say('WARNING', 'The correction filter was fed data faster than it can work.',
        'This happens if the averaging setting is too small.',
        'Use an averaging factor of 256 or more, or accept that the\n'
        'correction is switched off below that.')

if bypassed:
    say('WARNING', 'The droop correction is currently switched OFF.',
        'Either software asked for it, or the averaging factor is below 256.',
        'This is normal during some tests. If you did not intend it,\n'
        'set the averaging to 256 or more.')
else:
    say('OK', 'Droop correction is active.')

if werr:
    say('PROBLEM', 'Memory REFUSED at least one write since the last clear.',
        'The writes were issued and answered with an error, so nothing was'
        ' stored.',
        'Most likely cause: the board rebooted, which silently closes memory\n'
        'to FPGA-side writers again (TrustZone - see CHANGELOG 2026-07-30).\n'
        'Fix: sudo python3 diagnose_hp_ports.py --open-tz, then re-arm.\n'
        'Bitstreams built after 2026-07-30 carry the trusted badge and are\n'
        'immune; check the build fingerprint above.')
else:
    say('OK', 'Memory has not refused any writes.')


# ===========================================================================
heading('3b. Is memory open to the acquisition system?')
# ===========================================================================
#  The one setting that is neither in the design files nor in the bitstream:
#  the processor's TrustZone permission register (TZ_DDR_RAM). Its power-on
#  default closes ALL of memory to "untrusted" writers, and the write engine
#  in bitstreams built before 2026-07-30 presents the untrusted badge. This
#  cost the project two full days ("writes are accepted and never appear"),
#  because the setting silently reverts at EVERY REBOOT.
#
#  Bitstreams built after 2026-07-30 present the trusted badge and do not
#  care about this register. The check stays anyway: it is one read, and it
#  turns a silent reversion into a visible one.
# ===========================================================================
try:
    slcr = Reg(0xF8000000)          # processor system-control registers
    tz = slcr.r(0x430)              # TZ_DDR_RAM: 1 bit per 64 MB, 1 = open
    slcr.close()
    if tz == 0xFFFFFFFF:
        say('OK', 'Memory is open to FPGA-side writers (TrustZone).',
            'TZ_DDR_RAM = 0x%08X' % tz)
    else:
        say('WARNING', 'Memory is (partly) CLOSED to FPGA-side writers.',
            'TZ_DDR_RAM = 0x%08X - the power-on default is all closed.' % tz,
            'Harmless unless capturing to memory with a bitstream built\n'
            'before 2026-07-30. To open until the next reboot:\n'
            'sudo python3 diagnose_hp_ports.py --open-tz')
except Exception as e:
    say('WARNING', 'Could not read the TrustZone register.', str(e))


# ===========================================================================
heading('4. What is it currently set to?')
# ===========================================================================
ctrl = acq.r(0x00)
finc = acq.r(0x04)
dec  = acq.r(0x08) & 0xF
f_lo = finc * FS_CLK / (1 << 32)
R    = 1 << dec if 0 < dec < 16 else 0

print('    Running               : %s' % ('yes' if ctrl & 1 else 'no'))
print('    Listening at          : %.4f MHz' % (f_lo / 1e6))
print('    Averaging             : %d samples together' % R)
if R:
    f_out = FS_CLK / R
    print('    Samples produced      : %.1f per second' % f_out)
    print('    Frequency detail      : %.2f Hz apart, over a 16384-sample record'
          % (f_out / 16384))
    print('    Usable width          : +-%.1f kHz around the listening frequency'
          % (0.10 * f_out / 1e3))
print('    Test pattern mode     : %s' % ('ON - data is fake!' if ctrl & 4 else 'off'))
print('    Scope showing internals: %s' % ('yes' if ctrl & 8 else 'no'))
print('    Writing to memory     : %s' % ('yes' if ctrl & 16 else 'no'))
print('    Memory port           : %s' % ('axi1' if ctrl & 256 else 'axi0'))

if ctrl & 4:
    say('WARNING', 'Test pattern mode is ON.',
        'The numbers coming out are a counting sequence, not a measurement.',
        'Turn it off before taking real data.')

if ctrl & 256:
    # CTRL[8] = 1 selects axi1. On this board the boot software leaves axi1's
    # processor-side port (HP1) with a channel in 32-bit mode, which silently
    # stores only the lower half of every 64-bit sample: I arrives, Q never
    # does, and nothing flags an error. Found the hard way on 2026-07-30.
    say('WARNING', 'Memory port axi1 is selected - it DROPS HALF of every sample.',
        'axi1\'s processor-side port is misconfigured by the boot software:'
        ' only I is stored, Q is silently lost.',
        'Use axi0: clear CTRL bit 8, or leave AXI_PORT = 0 in the notebooks.\n'
        'axi1 is for diagnostics only. See CHANGELOG.md 2026-07-30.')


# ===========================================================================
heading('5. Is it actually producing samples?')
# ===========================================================================
if not (ctrl & 1):
    say('WARNING', 'The acquisition system is switched off.',
        'Nothing is being measured.',
        'This is normal if you have not started a test yet.')
else:
    c0 = acq.r(0x20); t0 = time.time()
    time.sleep(0.3)
    c1 = acq.r(0x20); t1 = time.time()
    rate = ((c1 - c0) & 0xFFFFFFFF) / (t1 - t0)
    expect = FS_CLK / R if R else 0

    if expect and abs(rate - expect) / expect < 0.05:
        say('OK', 'Producing samples at the expected rate.',
            'measured %.0f per second, expected %.0f' % (rate, expect))
    elif rate < 1:
        say('PROBLEM', 'No samples are being produced.',
            'The counter is not moving.',
            'Check the enable bit, then run Test Stage 2.')
    else:
        say('WARNING', 'Sample rate is not what it should be.',
            'measured %.0f per second, expected %.0f' % (rate, expect),
            'Run Test Stage 2, which checks this properly.')


# ===========================================================================
print('')
print('=' * 60)
print(' SUMMARY')
print('=' * 60)
print('   %d OK      %d warnings      %d problems' % (len(PASS), len(WARN), len(FAIL)))
print('')
if FAIL:
    print('   Deal with the PROBLEM entries above before taking any data.')
elif WARN:
    print('   Nothing is broken. Check the warnings are things you intended.')
else:
    print('   Everything looks healthy. Go ahead.')
print('')

ps.close()
acq.close()
