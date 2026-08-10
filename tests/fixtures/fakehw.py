# -*- coding: utf-8 -*-
"""A register-level mock of the Red Pitaya, good enough to run the whole
bench-coil notebook off the board.

It patches os.open / mmap.mmap / builtins.open, so EVERY line of the notebook's
own driver code runs unmodified - the Bus class, the poison check, the bounds
readback, tone_frac's least-squares projection, all of it. Only the silicon is
fake.

Physics modelled:
  * a parallel resonator with a chosen f0 and Q, plus an additive floor
  * a capacitive round trip with a chosen transfer, and an external amplifier
    with a gain and a compression knee
  * the feedback loop: Q_eff = Q0 / (1 - K cos phi), centre shifted by K sin phi,
    with an arbitrary loop phase so the narrowing phase must be FOUND
  * self-oscillation once K cos phi >= 1: full-scale input with the drive off
  * the digital resonator emulator, decoded from its own 18-bit coefficients
  * receiver noise, so a fit degrades at low drive exactly as it does on the board
"""
import struct, math, random
import numpy as _np

FS_CLK = 125e6
BUILD_ID = 0xFE76AE09
COUNT_SCALE = 5.3e8          # receiver counts per unit input fraction


class Scenario(object):
    name = 'baseline'
    f0 = 39.9414e6
    Q = 180.0
    floor_frac = 0.017        # off-resonance amplitude / on-resonance amplitude
    g_passive = 0.0158        # DAC -> coil -> ADC with no amplifier
    amp_gain_db = 33.7        # external amplifier in the drive path
    amp_knee_frac = 0.010     # input fraction at which the amplifier compresses
    phi_narrow = 330.0        # loop phase; must be found, never assumed
    df_per_k = 0.5            # centre shift in linewidths at K = 1, quadrature
    noise_counts = 1.0e5      # per single I/Q register read
    adc_dc_offset = 0.020     # fraction of full scale
    adc_broadband = 0.004     # fraction of full scale, rms
    emulator_present = True
    coil_present = True


class Region(object):
    """One mmap-able span of bytes."""

    def __init__(self, size):
        self.buf = bytearray(size)

    def __getitem__(self, s):
        return bytes(self.buf[s])

    def __setitem__(self, s, v):
        self.buf[s] = v

    def close(self):
        pass


class Board(object):
    ACQ, GEN, PS, EMU, SCOPE, SEQ = (0x40600000, 0x40200000, 0x40300000,
                                     0x40400000, 0x40100000, 0x40700000)
    DDR = 0x1E000000
    SC_NMAX = 1 << 14

    def __init__(self, scen=None):
        self.s = scen or Scenario()
        self.reg = {self.ACQ: {}, self.GEN: {}, self.PS: {}, self.EMU: {},
                    self.SCOPE: {}, self.SEQ: {}}
        self.ddr = Region(16 << 20)
        self.scope_buf = Region(0x40000)
        self.sample_counter = 0
        self.ddr_count = 0
        self.rng = random.Random(20260806)
        self.reg[self.ACQ][0x48] = BUILD_ID
        self.reg[self.SEQ][0x0C] = 0x5E900001
        self.gen_table_written = 0

    # ---------------- helpers ------------------------------------------------
    def _r(self, base, off, default=0):
        return self.reg[base].get(off, default)

    def f_gen(self):
        return self._r(self.GEN, 0x10) * FS_CLK / float(1 << 30)

    def drive(self):
        ctrl = self._r(self.GEN, 0x00)
        if ctrl == 0xC0:
            return 0.0
        return (self._r(self.GEN, 0x04) & 0x3FFF) / 8192.0

    # ---------------- the resonator ------------------------------------------
    def _emulator_on(self):
        return bool(self._r(self.EMU, 0x00) & 1) and self.s.emulator_present

    def _emu_pole(self):
        """Recover f0 and Q from the 18-bit coefficients actually written.

        Since 2026-08-07 the recursion is two-way look-ahead, so the pole it
        realises lives in COEF_C2/COEF_S2 (0x28/0x2C): r squared, turned by
        2*w0. COEF_C/COEF_S carry only the drive term. atan2 gives 2*w0 modulo
        2*pi and 2*w0 passes pi above 31.25 MHz, so the branch is resolved
        against the angle in COEF_C/COEF_S, which software wrote alongside."""
        def s18(v):
            v &= 0x3FFFF
            return v - (1 << 18) if v & 0x20000 else v
        ci = s18(self._r(self.EMU, 0x04))
        cs = s18(self._r(self.EMU, 0x08))
        c2 = s18(self._r(self.EMU, 0x28))
        s2 = s18(self._r(self.EMU, 0x2C))
        if c2 == 0 and s2 == 0:
            return None
        r2 = math.hypot(c2, s2) / 131072.0
        two_w0 = math.atan2(s2, c2)
        if ci or cs:                       # lift onto the branch nearest 2*w0
            hint = 2.0 * math.atan2(cs, ci)
            two_w0 += 2.0 * math.pi * round((hint - two_w0) / (2.0 * math.pi))
        f0 = (two_w0 / 2.0) / (2.0 * math.pi) * FS_CLK
        q = math.pi * (f0 / FS_CLK) / max(1.0 - math.sqrt(r2), 1e-12)
        return f0, q

    def _feedback(self):
        """(A, phi_deg) actually applied, undoing the notebook's latency term."""
        def s16(v):
            v &= 0xFFFF
            return v - (1 << 16) if v & 0x8000 else v
        c = s16(self._r(self.PS, 0x00)) / 16384.0
        q = s16(self._r(self.PS, 0x04)) / 16384.0
        A = math.hypot(c, q)
        if A <= 0:
            return 0.0, 0.0
        # the notebook subtracted 360 * LATENCY * f_ref / FS_CLK before writing
        f_ref = self.f_gen() or self.s.f0
        phi = math.degrees(math.atan2(q, c)) + 360.0 * 3.0 * f_ref / FS_CLK
        return A, phi

    def _tank(self):
        """(f0, Q, on-resonance amplitude scale, oscillating?) as fed back."""
        emu = self._emu_pole() if self._emulator_on() else None
        if emu is not None:
            f0, Q = emu
            g = 0.30                       # emulator replaces the input entirely
        else:
            if not self.s.coil_present:
                return None
            f0, Q = self.s.f0, self.s.Q
            g = self.s.g_passive * 10.0 ** (self.s.amp_gain_db / 20.0)
        A, phi = self._feedback()
        if A > 0:
            K = A * g * (1.0 if emu is not None else 1.0)
            rel = math.radians(phi - self.s.phi_narrow)
            denom = 1.0 - K * math.cos(rel)
            if denom <= 0.0:
                return f0, Q, g, True
            Q = Q / denom
            f0 = f0 + K * math.sin(rel) * self.s.df_per_k * (f0 / max(Q, 1e-9))
        return f0, Q, g, False

    def input_fraction(self, f=None):
        """Signal at IN1 as a fraction of full scale, at the drive frequency."""
        t = self._tank()
        if t is None:
            return 0.0
        f0, Q, g, osc = t
        if osc:
            return 1.0
        f = self.f_gen() if f is None else f
        d = self.drive()
        if d <= 0.0:
            return 0.0
        # amplifier compression
        eff = g
        if self.s.amp_gain_db > 0 and d > self.s.amp_knee_frac:
            eff = g * (self.s.amp_knee_frac / d) ** 0.5
        lw = f0 / max(Q, 1e-9)
        lor = 1.0 / math.sqrt(1.0 + (2.0 * (f - f0) / lw) ** 2)
        return d * eff * math.sqrt(lor ** 2 + self.s.floor_frac ** 2)

    # ---------------- register access ---------------------------------------
    def read(self, base, off):
        if base == self.ACQ:
            if off == 0x18 or off == 0x1C:
                amp = self.input_fraction() * COUNT_SCALE
                ph = 0.7 if off == 0x18 else 0.0
                v = amp * math.cos(ph) if off == 0x18 else amp * math.sin(0.7)
                v += self.rng.gauss(0.0, self.s.noise_counts)
                return int(v) & 0xFFFFFFFF
            if off == 0x20:
                self.sample_counter += int(0.10 * FS_CLK
                                           / (1 << max(self._r(base, 0x08), 1)))
                return self.sample_counter & 0xFFFFFFFF
            if off == 0x34:
                return self.ddr_count
            if off == 0x38:
                return 0
        if base == self.SCOPE and off == 0x04:
            return 0
        return self._r(base, off)

    def write(self, base, off, val):
        self.reg[base][off] = val & 0xFFFFFFFF
        if base == self.GEN and off >= 0x10000:
            self.gen_table_written += 1
        if base == self.SCOPE and off == 0x04 and (val & 1):
            self._fill_scope()
            self.reg[base][off] = 0
        if base == self.ACQ and off == 0x00 and (val & 16):
            self._fill_ddr()

    # ---------------- bulk data ---------------------------------------------
    def _fill_scope(self):
        n = self._r(self.SCOPE, 0x10, self.SC_NMAX - 1) + 1
        dec = max(1, self._r(self.SCOPE, 0x14, 1))
        fs = FS_CLK / dec
        f = self.f_gen()
        a = self.input_fraction() * 8191.0
        dc = self.s.adc_dc_offset * 8191.0
        nz = self.s.adc_broadband * 8191.0
        i = _np.arange(n)
        v = a * _np.sin(2.0 * _np.pi * f * i / fs) + dc
        v = v + _np.random.RandomState(self.rng.randrange(1 << 30)).normal(0, nz, n)
        v = _np.clip(_np.round(v), -8191, 8191).astype(_np.int32) & 0x3FFF
        self.scope_buf.buf[0x10000:0x10000 + 4 * n] = v.astype('<u4').tobytes()

    def _fill_ddr(self):
        lo = self._r(self.ACQ, 0x04)
        f = lo * FS_CLK / float(1 << 32)
        amp = 0.0
        t = self._tank()
        if t is not None and self.drive() > 0:
            amp = self.input_fraction(f) * COUNT_SCALE
        n = 4096
        self.ddr_count = n
        rs = _np.random.RandomState(self.rng.randrange(1 << 30))
        iv = (amp + rs.normal(0, self.s.noise_counts, n)).astype(_np.int32)
        qv = rs.normal(0, self.s.noise_counts, n).astype(_np.int32)
        out = _np.empty(2 * n, dtype=_np.int32)
        out[0::2] = iv
        out[1::2] = qv
        self.ddr.buf[0:8 * n] = out.astype('<i4').tobytes()


# ============================================================================
#  the patches
# ============================================================================
_BOARD = None
_FDS = {}
_NEXT_FD = [900]


class FakeMap(object):
    def __init__(self, base, span):
        self.base = base
        self.span = span

    def _region(self):
        b = self.base
        if b == Board.SCOPE:
            return _BOARD.scope_buf
        if b == Board.DDR:
            return _BOARD.ddr
        return None

    def __getitem__(self, s):
        reg = self._region()
        if reg is not None and (self.base == Board.DDR or s.start >= 0x10000):
            return reg[s]
        return struct.pack('<I', _BOARD.read(self.base, s.start))

    def __setitem__(self, s, v):
        reg = self._region()
        if reg is not None and (self.base == Board.DDR or s.start >= 0x10000):
            reg[s] = v
            return
        if len(v) == 4:
            _BOARD.write(self.base, s.start, struct.unpack('<I', bytes(v))[0])
        else:                                   # the poison fill
            reg = _BOARD.ddr
            reg[s] = v

    def close(self):
        pass


def install(scenario=None, target_globals=None):
    """Patch os/mmap/open in `target_globals` (or globally) and return the Board."""
    global _BOARD
    import os as _os, mmap as _mmap, io as _io
    _BOARD = Board(scenario)

    real_open = open

    def fake_os_open(path, *a, **k):
        _NEXT_FD[0] += 1
        return _NEXT_FD[0]

    def fake_os_close(fd):
        return None

    def fake_mmap(fd, span, offset=0, **k):
        return FakeMap(offset, span)

    def fake_open(path, mode='r', *a, **k):
        p = str(path).replace('\\', '/')
        if 'device' in p and p.endswith('reg'):
            # start = 0, size = 0x1E000000, so MEM_START lands at 0x1E000000
            return _io.BytesIO(struct.pack('>II', 0, Board.DDR))
        return real_open(path, mode, *a, **k)

    g = target_globals
    g['os'] = type('os_shim', (), {'open': staticmethod(fake_os_open),
                                   'close': staticmethod(fake_os_close),
                                   'O_RDWR': 0, 'O_SYNC': 0,
                                   'path': _os.path,
                                   'environ': _os.environ})
    g['mmap'] = type('mmap_shim', (), {'mmap': staticmethod(fake_mmap)})
    g['open'] = fake_open
    return _BOARD
