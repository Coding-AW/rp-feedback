import numpy as np

# ---- Fixed-point params (must match the HDL) ----
FRAC   = 14                 # coefficient fractional bits (Q2.14)
COEFF  = lambda x: int(np.clip(round(x * (1<<FRAC)), -(1<<15), (1<<15)-1))  # signed 16-bit
DATW   = 14                 # data width
DMAX   = (1<<(DATW-1)) - 1
DMIN   = -(1<<(DATW-1))
FS     = 125e6              # ADC/DAC sample clock

def sat(x):
    return max(DMIN, min(DMAX, x))

def hw_model(x, phase_deg, gain, fsig, depth=1024):
    """Bit-accurate emulation of red_pitaya_phaseshift datapath."""
    phi = np.deg2rad(phase_deg)
    ci  = COEFF(gain*np.cos(phi))     # A cos  -> reg
    cq  = COEFF(gain*np.sin(phi))     # A sin  -> reg
    D   = FS/(4.0*fsig)               # quarter-period delay in samples
    dly = int(np.floor(D)); dly = min(dly, depth-2)
    delta = int(round((D - np.floor(D)) * (1<<FRAC)))   # Q0.14, 0..16384
    delta = min(delta, (1<<FRAC))
    w0 = (1<<FRAC) - delta            # (1-delta)
    w1 = delta
    # shift register of past samples: buf[0]=newest
    buf = [0]*depth
    y = np.zeros(len(x), dtype=int)
    for n, s in enumerate(x):
        buf.insert(0, int(round(s)))          # push newest
        buf.pop()                              # keep depth
        i_samp = buf[0]                        # cos tap at n=0
        qf = buf[dly]; qc = buf[dly+1]         # fractional-delay taps
        q  = (w0*qf + w1*qc) >> FRAC           # blended Q (arith shift)
        acc = (ci*i_samp + cq*q) >> FRAC       # weighted sum, rescale
        y[n] = sat(acc)
    return y, dict(ci=ci, cq=cq, dly=dly, delta=delta, D=D)

def measure(x, y, fsig, fs=FS, skip=4000):
    """Fit amplitude & phase of y relative to x at fsig (skip startup transient)."""
    n = np.arange(len(x))
    c = np.cos(2*np.pi*fsig*n/fs); s = np.sin(2*np.pi*fsig*n/fs)
    def phasor(v):
        v = v[skip:]; cc=c[skip:]; ss=s[skip:]
        I = 2*np.mean(v*cc); Q = -2*np.mean(v*ss)
        return I + 1j*Q
    px, py = phasor(x.astype(float)), phasor(y.astype(float))
    r = py/px
    return abs(r), np.rad2deg(np.angle(r))

# ---- Sweep ----
fsig = 740e3          # test signal (paper's axial freq); try others too
A_in = 6000.0         # input amplitude in ADC counts (~0.73 of full scale)
N    = 40000
n    = np.arange(N)
x    = A_in*np.cos(2*np.pi*fsig*n/FS)

print(f"{'set phi':>8} {'gain':>5} | {'meas gain':>9} {'meas phi':>9} | {'d phi':>7} {'d gain%':>8}")
for gain in (1.0, 0.5):
    for phase in (0, 30, 45, 90, 135, 180, 270, -45):
        y, info = hw_model(x, phase, gain, fsig)
        mgain, mphi = measure(x, y, fsig)
        # expected: output = input phase-shifted by -phase (lag). measured angle ~ -phase
        dphi = ((mphi - (-phase) + 180) % 360) - 180
        dg   = 100*(mgain - gain)/gain
        print(f"{phase:8.0f} {gain:5.2f} | {mgain:9.4f} {mphi:9.3f} | {dphi:7.3f} {dg:8.3f}")

# frequency robustness at fixed phase
print("\nFrequency check @ phi=45, gain=1.0:")
for f in (100e3, 250e3, 500e3, 740e3, 1e6):
    xx = A_in*np.cos(2*np.pi*f*n/FS)
    y, info = hw_model(xx, 45, 1.0, f)
    mgain, mphi = measure(xx, y, f)
    dphi = ((mphi - (-45) + 180) % 360) - 180
    print(f"  f={f/1e3:6.0f} kHz  D={info['D']:7.2f}  meas gain={mgain:.4f}  d_phi={dphi:+.3f} deg")
