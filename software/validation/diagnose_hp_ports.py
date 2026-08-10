#!/usr/bin/env python3
"""
diagnose_hp_ports.py  -  run on the BOARD, as root:   sudo python3 diagnose_hp_ports.py

===============================================================================
 WHY THIS SCRIPT EXISTS
===============================================================================
 Test Stage 6 (2026-07-30): every memory write from the acquisition system is
 answered with a refusal, identically on axi0 and axi1, while the processor
 can write the same addresses without trouble. Every piece of logic in the
 design files has been checked and cleared, and so has the Zynq block design
 (all ports enabled, memory mapped). What remains is the processor's RUNTIME
 configuration - settings written by the boot software on the SD card, which
 exist in no design file and are not part of the bitstream.

 Two such settings can produce exactly this symptom:

 1. TRUSTZONE (the security doorman).  Every memory transaction carries a
    badge: "trusted" or "untrusted". The write engine the acquisition system
    uses (Red Pitaya's own axi_master.v) presents the UNTRUSTED badge.
    Register TZ_DDR_RAM holds one bit per 64 MB slice of memory: bit set =
    untrusted writers allowed into that slice. Its power-on default is 0 -
    REFUSE EVERYTHING. If the boot software never opens it, untrusted writes
    are accepted, then refused, everywhere, forever - while the processor
    (trusted badge) works normally. That is our symptom, exactly.

 2. PORT WIDTH.  Each high-performance (HP) port has a runtime 32/64-bit
    switch (one bit in its AFI control registers). Our writes are 64-bit.
    If the switch says 32, every burst is answered with an error.

 This script READS those registers and explains them. Reading changes nothing.
 With --open-tz or --set-afi-64 it will also FIX them (see notes at the end).

 SAFETY: these are processor-system registers at 0xF8000000/0xF8008000/
 0xF8009000, read via /dev/mem. This is the same mechanism every Red Pitaya
 tool uses. It does NOT touch the FPGA's own register bus at 0x40xxxxxx, so
 the "read registers one at a time" lock-up trap does not apply here.
===============================================================================
"""

import argparse, mmap, os, struct, sys

# ---------------------------------------------------------------------------
#  Register addresses (Zynq-7000 Technical Reference Manual, appendix B)
# ---------------------------------------------------------------------------
SLCR_BASE   = 0xF8000000   # System Level Control Registers
SLCR_LOCK   = 0x004        # write 0x767B here to lock the SLCR against writes
SLCR_UNLOCK = 0x008        # write 0xDF0D here to unlock
SLCR_LOCKSTA= 0x00C        # 1 = locked
TZ_DDR_RAM  = 0x430        # TrustZone: 1 bit per 64 MB of memory, 1 = open
LVL_SHFTR   = 0x900        # level shifters between processor and FPGA halves

AFI_BASES = {0: 0xF8008000, 1: 0xF8009000}   # per-port AFI register blocks
AFI_RDCHAN_CTRL = 0x00     # bit 0: 1 = port is in 32-bit mode for READS
AFI_WRCHAN_CTRL = 0x10     # bit 0: 1 = port is in 32-bit mode for WRITES

CAPTURE_ADDR = 0x1E000000  # where Stage 6 tried to write - used to say which
                           # TrustZone bit matters for it

def open_mem(base):
    """Map one 4096-byte page of physical registers into this program."""
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    m  = mmap.mmap(fd, 4096, mmap.MAP_SHARED,
                   mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
    os.close(fd)
    return m

def r32(m, off):
    return struct.unpack_from("<I", m, off)[0]

def w32(m, off, val):
    struct.pack_into("<I", m, off, val)

def main():
    ap = argparse.ArgumentParser(description="Diagnose why the HP memory ports refuse writes")
    ap.add_argument("--open-tz", action="store_true",
                    help="open all of memory to untrusted (FPGA-side) writers")
    # KNOWN NOT TO WORK ON THIS BOARD (2026-07-30): the processor accepts READS
    # of the AFI width registers but kills the process with "Bus error" on the
    # first WRITE to them. Nothing is harmed and nothing is changed when that
    # happens. Consequence: HP1's 32-bit read channel cannot be corrected from
    # Linux here, which is why the project standardised on axi0 (HP0, correctly
    # configured) instead - see CHANGELOG.md 2026-07-30. The flag is kept for
    # boards where the write may be allowed.
    ap.add_argument("--set-afi-64", action="store_true",
                    help="set HP0 and HP1 to 64-bit mode (crashes with 'Bus error'"
                         " on this board - harmless but ineffective; use axi0 instead)")
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("needs root: run with sudo")

    slcr = open_mem(SLCR_BASE)
    afi  = {n: open_mem(b) for n, b in AFI_BASES.items()}

    # -----------------------------------------------------------------------
    #  READ AND EXPLAIN
    # -----------------------------------------------------------------------
    tz      = r32(slcr, TZ_DDR_RAM)
    locked  = r32(slcr, SLCR_LOCKSTA) & 1
    shftr   = r32(slcr, LVL_SHFTR)
    tz_bit  = CAPTURE_ADDR // (64 * 1024 * 1024)   # which 64 MB slice 0x1E000000 is in

    print("=" * 70)
    print(" HP-port diagnosis  -  values read from the running board")
    print("=" * 70)
    print()
    print(" TrustZone memory permissions (TZ_DDR_RAM, 0xF8000430): 0x%08X" % tz)
    print("   one bit per 64 MB slice of memory, 1 = untrusted writers allowed")
    print("   the Stage 6 capture region 0x%08X is slice %d (bit %d)"
          % (CAPTURE_ADDR, tz_bit, tz_bit))
    if tz == 0:
        print("   >>> ALL ZERO: every slice is closed to untrusted writers.")
        print("   >>> This is the power-on default, and it refuses every write")
        print("   >>> from the acquisition system while letting the processor")
        print("   >>> through - the Stage 6 symptom, exactly.")
        print("   >>> Fix: run again with  --open-tz   (then re-run Stage 6,")
        print("   >>> no rebuild needed)")
    elif not (tz >> tz_bit) & 1:
        print("   >>> The slice the capture uses is CLOSED. Fix: --open-tz")
    else:
        print("   OK - the capture region is open, TrustZone is not the cause")
    print()

    for n in (0, 1):
        rd = r32(afi[n], AFI_RDCHAN_CTRL)
        wr = r32(afi[n], AFI_WRCHAN_CTRL)
        print(" Port HP%d width settings (AFI%d at 0x%08X):" % (n, n, AFI_BASES[n]))
        print("   read-channel control  = 0x%08X  -> %s"
              % (rd, "32-BIT  <<< mismatch, ours are 64" if rd & 1 else "64-bit, correct"))
        print("   write-channel control = 0x%08X  -> %s"
              % (wr, "32-BIT  <<< mismatch, ours are 64" if wr & 1 else "64-bit, correct"))
    print()
    print(" Level shifters (0xF8000900): 0x%08X  -> %s"
          % (shftr, "enabled, correct" if shftr & 0xF == 0xF else "NOT fully enabled - unexpected"))
    print(" Register write-protect (SLCR lock): %s" % ("locked" if locked else "unlocked"))
    print()

    # -----------------------------------------------------------------------
    #  FIXES  -  only if asked for on the command line
    # -----------------------------------------------------------------------
    if args.open_tz or args.set_afi_64:
        if locked:
            w32(slcr, SLCR_UNLOCK, 0xDF0D)     # standard unlock code, from the manual

        if args.open_tz:
            w32(slcr, TZ_DDR_RAM, 0xFFFFFFFF)  # open every slice
            print(" APPLIED: TrustZone opened. TZ_DDR_RAM now 0x%08X"
                  % r32(slcr, TZ_DDR_RAM))

        if args.set_afi_64:
            for n in (0, 1):
                w32(afi[n], AFI_RDCHAN_CTRL, r32(afi[n], AFI_RDCHAN_CTRL) & ~1)
                w32(afi[n], AFI_WRCHAN_CTRL, r32(afi[n], AFI_WRCHAN_CTRL) & ~1)
            print(" APPLIED: HP0 and HP1 set to 64-bit mode")

        if locked:
            w32(slcr, SLCR_LOCK, 0x767B)       # restore the lock we found

        print()
        print(" NOTE: these settings live in the processor, not on the SD card,")
        print(" so they RESET AT EVERY REBOOT. Once Stage 6 confirms the fix,")
        print(" make it permanent - either add this script to the board's boot")
        print(" sequence, or ask for the one-line design change that makes the")
        print(" write engine present the trusted badge instead.")

if __name__ == "__main__":
    main()
