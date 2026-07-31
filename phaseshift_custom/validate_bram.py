import numpy as np
FRAC=14; SCALE=1<<FRAC; FS=125e6; DWI=14
DMAX=(1<<(DWI-1))-1; DMIN=-(1<<(DWI-1))
def s16(x): return int(np.clip(round(x),-32768,32767))
def sat(x): return max(DMIN,min(DMAX,x))

def bram_rtl(x, phase_deg, gain, fsig, DEPTH=1024):
    """Cycle-accurate model of the BRAM circular-buffer RTL."""
    phi=np.deg2rad(phase_deg)
    ci=s16(gain*np.cos(phi)*SCALE); cq=s16(gain*np.sin(phi)*SCALE)
    D=FS/(4*fsig); dly=min(int(np.floor(D)),DEPTH-2)
    delta=min(int(round((D-np.floor(D))*SCALE)),SCALE-1)
    w0=SCALE-delta; w1=delta
    mem=[0]*DEPTH
    # FIX 6: acc_reg and i_byp are the new pipeline stage in the output path.
    wp=0; i_d1=0; q_flr=0; q_cel=0; q_samp=0; i_reg=0; acc_reg=0; i_byp=0; out_a=0
    y=np.zeros(len(x),dtype=int)
    M=DEPTH-1
    for n,s in enumerate(x):
        s=int(round(s))
        addr_f=(wp-dly)&M
        addr_c=(wp-dly-1)&M
        # next-state (nonblocking): reads use OLD mem, arithmetic uses CURRENT regs
        n_q_flr=mem[addr_f]
        n_q_cel=mem[addr_c]
        n_i_d1=s
        n_q_samp=(w0*q_flr + w1*q_cel)>>FRAC
        n_i_reg=i_d1
        # FIX 6: the sum is now registered, and the clipping happens one clock
        # later on the registered value. i_byp keeps the bypass path aligned so
        # that switching bypass does not change the latency.
        n_acc_reg=ci*i_reg + cq*q_samp
        n_i_byp=i_reg
        n_out=sat(acc_reg>>FRAC)
        # commit
        mem[wp]=s
        wp=(wp+1)&M
        q_flr,q_cel,i_d1,q_samp,i_reg=n_q_flr,n_q_cel,n_i_d1,n_q_samp,n_i_reg
        acc_reg,i_byp,out_a=n_acc_reg,n_i_byp,n_out
        y[n]=out_a
    return y,dict(ci=ci,cq=cq,dly=dly,delta=delta,D=D)

def measure(x,y,fsig,fs=FS,skip=6000):
    n=np.arange(len(x)); c=np.cos(2*np.pi*fsig*n/fs); s=np.sin(2*np.pi*fsig*n/fs)
    def ph(v):
        v=v[skip:]; cc=c[skip:]; ss=s[skip:]
        return 2*np.mean(v*cc)-2j*np.mean(v*ss)
    r=ph(y.astype(float))/ph(x.astype(float))
    return abs(r),np.rad2deg(np.angle(r))

fsig=740e3; A=6000.0; N=40000; n=np.arange(N)
x=A*np.cos(2*np.pi*fsig*n/FS)
print("BRAM RTL model — expect meas phase ~= -set phase, gain ~= set gain")
print(f"{'phi':>6} {'gain':>5} | {'m_gain':>7} {'m_phi':>8} | {'dphi':>6} {'dg%':>6}")
worst_p=0; worst_g=0
for gain in (1.0,0.5):
    for phase in (0,30,45,90,135,180,270,-45):
        y,info=bram_rtl(x,phase,gain,fsig)
        mg,mp=measure(x,y,fsig)
        dphi=((mp-(-phase)+180)%360)-180
        dg=100*(mg-gain)/gain
        worst_p=max(worst_p,abs(dphi)); worst_g=max(worst_g,abs(dg))
        print(f"{phase:6.0f} {gain:5.2f} | {mg:7.4f} {mp:8.3f} | {dphi:6.3f} {dg:6.3f}")
print(f"\nWORST phase err {worst_p:.3f} deg,  WORST gain err {worst_g:.3f} %")

# --- measure pipeline latency L (samples) across frequency at phi=0 ---
print("\nLatency check (phi=0): offset should be a CONSTANT number of samples")
for f in (250e3,500e3,740e3,1e6):
    xx=A*np.cos(2*np.pi*f*n/FS)
    y,_=bram_rtl(xx,0,1.0,f)
    mg,mp=measure(xx,y,f)
    L=(-mp/360.0)*(FS/f)
    print(f"  f={f/1e3:6.0f} kHz  offset={mp:7.3f} deg  -> L={L:5.3f} samples")

# --- now add host-side latency compensation and re-verify full sweep ---
L_PIPE = 3   # measured constant pipeline latency in samples
# FIX 6 changed this from 2 to 3: the output stage was split across two clock
# cycles to meet timing. The latency check above measures it independently and
# must agree - if it prints 3.000 and this says 2, every phase comes out wrong
# by 360*f_sig/f_clk degrees (2.1 deg at 740 kHz, 115 deg at 40 MHz).
def bram_rtl_comp(x, phase_deg, gain, fsig, DEPTH=1024):
    # compensate: request phi_eff so output (which lags by L) lands on phi
    phi_eff = phase_deg - 360.0*L_PIPE*fsig/FS
    return bram_rtl(x, phi_eff, gain, fsig, DEPTH)

print(f"\nWith host latency compensation (L={L_PIPE}):")
print(f"{'phi':>6} {'gain':>5} | {'m_gain':>7} {'m_phi':>8} | {'dphi':>6}")
wp=0
for gain in (1.0,0.5):
    for phase in (0,30,45,90,135,180,270,-45):
        y,info=bram_rtl_comp(x,phase,gain,fsig)
        mg,mp=measure(x,y,fsig)
        dphi=((mp-(-phase)+180)%360)-180
        wp=max(wp,abs(dphi))
        print(f"{phase:6.0f} {gain:5.2f} | {mg:7.4f} {mp:8.3f} | {dphi:6.3f}")
print(f"\nWORST phase err after compensation: {wp:.3f} deg")
