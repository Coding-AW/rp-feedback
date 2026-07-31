#!/usr/bin/env python3
"""
WHAT DOES THIS BOARD DO WITH ITS MEMORY?  -  read-only, changes nothing.

    sudo python3 show_memory_map.py

Run this before touching any boot setting. It answers three questions:

    how much RAM is fitted?
    how much of it has Linux claimed?
    has anything already been set aside for the programmable logic?

Every one of these is a read. Nothing is written, nothing is mounted, nothing
is rebooted. It is safe to run at any time, including while a measurement is
going on.

WHY IT EXISTS
-------------
Test Stage 6 writes samples straight into physical memory and therefore needs a
region Linux is not using. The usual advice is "add mem= to the boot arguments",
and on some Red Pitaya images that means editing a file called uEnv.txt.

**This image has no uEnv.txt.** Its boot partition holds `u-boot.scr` and
`devicetree.dtb`, both compiled, and it is mounted read-only. So the usual
advice does not apply, and guessing at it would be a good way to end up with a
board that does not boot.

Many Red Pitaya images already reserve a block for exactly this purpose. If this
one does, nothing needs changing at all - which is the first thing worth finding
out, and what this prints.
"""

import os
import re
import struct
import subprocess
import sys

DT = '/sys/firmware/devicetree/base'
if not os.path.isdir(DT):
    DT = '/proc/device-tree'


def rule(t=''):
    print('')
    print('-' * 70)
    if t:
        print(' ' + t)
        print('-' * 70)


def be32(b, i=0):
    return struct.unpack('>I', b[i * 4:i * 4 + 4])[0]


def read(path, binary=False):
    try:
        with open(path, 'rb' if binary else 'r') as fh:
            return fh.read()
    except (IOError, OSError):
        return None


def mb(n):
    return '%.1f MB' % (n / 1024.0**2)


# ---------------------------------------------------------------------------
print('=' * 70)
print(' Memory map of this board          (read-only: nothing is changed)')
print('=' * 70)

# --- 1. how much RAM is fitted ---------------------------------------------
rule('1. RAM HANDED TO LINUX, according to the device tree')
print('   NOTE: this is not how much RAM is fitted. It is how much the device')
print('   tree declares. Red Pitaya images routinely declare LESS than is')
print('   fitted, precisely so the top of memory is left for the logic.')
print('')
total = base = None
for p in ('memory/reg', 'memory@0/reg'):
    blob = read(os.path.join(DT, p), binary=True)
    if blob and len(blob) >= 8:
        base, total = be32(blob, 0), be32(blob, 1)
        print('   0x%08X .. 0x%08X    %s' % (base, base + total - 1, mb(total)))
        break
if total is None:
    print('   could not read it')

# --- 2. what Linux has claimed ---------------------------------------------
rule('2. What Linux has claimed  (/proc/iomem)')
iom = read('/proc/iomem')
top = 0
if iom:
    lines = [l for l in iom.split('\n') if 'System RAM' in l]
    for line in lines:
        print('   ' + line.strip())
        lo, hi = line.split(':')[0].strip().split('-')
        top = max(top, int(hi, 16))
    if not lines:
        print('   no System RAM entries at all')
    elif top == 0:
        print('')
        print('   Every address reads as zero, which is what a NON-ROOT user sees.')
        print('   Re-run with: sudo python3 show_memory_map.py')
else:
    print('   could not read /proc/iomem - run as root')

# --- 3. anything already reserved ------------------------------------------
rule('3. Already reserved for hardware  (device tree)')
resv = os.path.join(DT, 'reserved-memory')
regions = []
found_any = False
if os.path.isdir(resv):
    for name in sorted(os.listdir(resv)):
        node = os.path.join(resv, name)
        if not os.path.isdir(node):
            continue
        blob = read(os.path.join(node, 'reg'), binary=True)
        if blob and len(blob) >= 8:
            a, n = be32(blob, 0), be32(blob, 1)
            print('   %-28s 0x%08X .. 0x%08X   %s' % (name, a, a + n - 1, mb(n)))
            regions.append((name, a, n))
            found_any = True
        else:
            print('   %-28s (dynamically placed, no fixed address)' % name)
            found_any = True
if not found_any:
    print('   nothing declared here')
else:
    print('')
    print('   These are blocks the kernel has been told to set aside for hardware.')
    print('   Linux will not allocate them, which is exactly what is needed here.')

# --- 4. what the kernel was told at boot -----------------------------------
rule('4. Boot arguments')
cmd = read('/proc/cmdline')
print('   running kernel :')
print('      ' + (cmd.strip() if cmd else '?'))
if cmd and re.search(r'\bmem=', cmd):
    print('   -> a mem= limit IS set')
else:
    print('   -> no mem= limit')

dtb_args = read(os.path.join(DT, 'chosen/bootargs'), binary=True)
if dtb_args:
    txt = dtb_args.decode('utf-8', 'replace').replace('\x00', '').strip()
    if txt:
        print('')
        print('   from the device tree (chosen/bootargs):')
        print('      ' + txt)

# --- 5. where those arguments come from ------------------------------------
rule('5. Where the boot arguments are set on THIS image')
print('   boot partition:')
mnt = read('/proc/mounts') or ''
for line in mnt.split('\n'):
    if 'mmcblk0p1' in line:
        parts = line.split()
        opts = parts[3].split(',')
        rw = 'read-only' if 'ro' in opts else 'WRITABLE'
        print('      %s on %-16s %s' % (parts[0], parts[1], rw))

for f in ('/boot/uEnv.txt', '/boot/u-boot.scr', '/boot/devicetree.dtb', '/boot/dtraw.dts'):
    print('   %-24s %s' % (f, 'present' if os.path.exists(f) else 'not present'))

if os.path.exists('/boot/u-boot.scr'):
    print('')
    print('   u-boot.scr is a COMPILED script. Its text can be read but not edited')
    print('   directly. What it sets:')
    try:
        out = subprocess.check_output(['strings', '/boot/u-boot.scr'])
        if not isinstance(out, str):
            out = out.decode('utf-8', 'replace')
        for line in out.split('\n'):
            if 'bootargs' in line or 'mem=' in line:
                print('      ' + line.strip()[:200])
    except Exception:
        print('      (could not run strings)')

if os.path.exists('/boot/dtraw.dts'):
    src = read('/boot/dtraw.dts', binary=True)
    src = src.decode('utf-8', 'replace') if src else None
    if src and 'reserved-memory' in src:
        print('')
        print('   dtraw.dts contains a reserved-memory section:')
        i = src.index('reserved-memory')
        for line in src[i:i + 700].split('\n')[:18]:
            print('      ' + line.rstrip())

# --- 6. the verdict ---------------------------------------------------------
rule('VERDICT')

#  Rank the candidates. A declared reserved-memory block is the best answer:
#  the kernel has been told about it and told not to use it, which is a promise
#  rather than an observation. The gap above the declared memory is next - it is
#  genuinely unreachable by Linux, but only exists if more RAM is fitted than
#  was declared, which has to be inferred rather than read.
candidates = []
for name, a, n in regions:
    if n >= 1024**2:
        candidates.append((n, a, n, 'reserved-memory: %s' % name))

if total is not None:
    declared_end = base + total
    for fitted in (512 * 1024**2, 1024 * 1024**2):
        if fitted > declared_end:
            gap = fitted - declared_end
            candidates.append((gap // 2, declared_end, gap,
                               'above the declared memory (only if %d MB is fitted)'
                               % (fitted // 1024**2)))
            break

if candidates:
    candidates.sort(reverse=True)
    print('   USABLE REGIONS FOUND. Nothing needs changing.')
    print('')
    for _, a, n, why in candidates:
        print('   0x%08X .. 0x%08X   %9s   %s' % (a, a + n - 1, mb(n), why))
    print('')
    best_a, best_n, best_why = candidates[0][1], candidates[0][2], candidates[0][3]
    start = (best_a + 0xFFF) & ~0xFFF
    stop  = min(start + 8 * 1024**2, best_a + best_n)
    print('   Best choice: %s' % best_why)
    print('')
    print('   Put these into Test Stage 6, Step 1:')
    print('')
    print('       MEM_START = 0x%08X' % start)
    print('       MEM_STOP  = 0x%08X' % stop)
    print('       MEM_OK    = True')
    print('')
    print('   That is %s, room for %d samples.' % (mb(stop - start), (stop - start) // 8))
    print('   Step 1 will still probe it before anything is armed, and Step 2')
    print('   still does a 4 kB trial capture first.')
    if 'labuf' in best_why:
        print('')
        print('   One caveat: labuf is Red Pitaya\'s logic-analyser buffer. It is')
        print('   free unless you run their logic analyser application. Do not run')
        print('   both at once.')
else:
    print('   NOTHING USABLE FOUND.')
    print('')
    print('   No reserved-memory block big enough, and no evidence of RAM beyond')
    print('   what was declared. Do not guess an address. Options, in order:')
    print('     1. Ask whoever set this board up.')
    print('     2. Use a Red Pitaya image that reserves a buffer.')
    print('     3. Rebuild u-boot.scr or the device tree - a real change to how')
    print('        the board boots. Image the SD card first.')

print('')
print('=' * 70)
print(' Nothing was changed by running this.')
print('=' * 70)
