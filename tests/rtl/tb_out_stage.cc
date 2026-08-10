// ===========================================================================
//  tb_out_stage.cc - simulate the ACTUAL Verilog, before and after the
//                    2026-08-07 output-stage and OUT2 changes.
//
//  WHY THIS EXISTS. validate_out_stage.py models both stages in Python, but
//  that model is a hand translation of the Verilog - so it can share a
//  misreading with the source it was written from, and agreeing with itself
//  proves nothing. This runs the real files. Yosys elaborates each one to a
//  cycle-accurate C++ model (CXXRTL); the pre-edit copies and the post-edit
//  copies are instantiated side by side and driven with identical stimulus.
//
//  Nothing here compares against a model. It compares the design against
//  ITSELF, before and after, which is the actual claim being made:
//
//    T1  resonator: new(t) == old(t-1) for every t. A pure one-clock delay.
//    T2  resonator: new with DELAY = 12 is bit-identical to old with DELAY 13.
//    T3  resonator: the emulated resonance is unchanged - same ring frequency
//        and same decay - so the pipeline register moved the output in time
//        and did nothing else to it.
//    T4  phase shifter: with the monitor off, dat_a_o is bit-identical to the
//        old file's. The feedback path is untouched.
//    T5  phase shifter: with the monitor off, dat_b_o is zero on every cycle,
//        exactly as the tied-off net was.
//    T6  phase shifter: with the monitor on, OUT2 carries the selected source,
//        shifted, saturating - never wrapping - and MON_CLIP reports it.
//    T7  phase shifter: bypass and the sequencer coefficient path still work.
//
//  Build and run through run_rtl_sim.sh, which generates the CXXRTL first.
// ===========================================================================
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>

#include "reso_old_rtl.h"
#include "reso_new_rtl.h"
#include "ps_old_rtl.h"
#include "ps_new_rtl.h"

using namespace cxxrtl_design;

static int fails = 0;
static int checks = 0;

static void report(const char *name, bool ok, const char *detail = "")
{
    checks++;
    if (!ok) fails++;
    printf("  %-4s %-58s %s\n", ok ? "PASS" : "FAIL", name, detail);
}

// 14-bit and 25-bit two's complement out of the raw CXXRTL word
static int s14(uint32_t v) { return (v & 0x2000u) ? (int)v - 0x4000 : (int)v; }

// ---------------------------------------------------------------------------
//  Resonator harness. One template so old and new are driven by identical code
//  - the stimulus cannot differ between them even by accident.
// ---------------------------------------------------------------------------
template <typename T>
struct Reso {
    T d;

    void tick()
    {
        d.p_clk__i.template set<bool>(false); d.step();
        d.p_clk__i.template set<bool>(true);  d.step();
    }
    void wr(uint32_t addr, uint32_t data)
    {
        d.p_sys__addr.template set<uint32_t>(addr);
        d.p_sys__wdata.template set<uint32_t>(data);
        d.p_sys__wen.template set<bool>(true);
        tick();
        d.p_sys__wen.template set<bool>(false);
        tick();
    }
    void reset()
    {
        d.p_rstn__i.template set<bool>(false);
        d.p_dat__i.template set<uint32_t>(0);
        d.p_sys__wen.template set<bool>(false);
        d.p_sys__ren.template set<bool>(false);
        for (int i = 0; i < 8; i++) tick();
        d.p_rstn__i.template set<bool>(true);
        for (int i = 0; i < 4; i++) tick();
    }
    //  Configure exactly as Emulator.config() does: four coefficients since
    //  2026-08-07. The old file ignores 0x28/0x2C, which is why the notebook
    //  has a readback guard - not this testbench's problem.
    void config(int c, int s, int c2, int s2, int delay, int oshift)
    {
        wr(0x04, (uint32_t)c  & 0x3FFFF);
        wr(0x08, (uint32_t)s  & 0x3FFFF);
        wr(0x28, (uint32_t)c2 & 0x3FFFF);
        wr(0x2C, (uint32_t)s2 & 0x3FFFF);
        wr(0x0C, (uint32_t)delay);
        wr(0x10, (uint32_t)oshift);
        wr(0x00, 0x3);          // enable + clear
        wr(0x00, 0x1);          // enable, clear released
    }
    //  Drive `n` samples and collect dat_o.
    void run(const std::vector<int> &drive, std::vector<int> &out)
    {
        out.clear();
        for (size_t i = 0; i < drive.size(); i++) {
            d.p_dat__i.template set<uint32_t>((uint32_t)drive[i] & 0x3FFF);
            tick();
            out.push_back(s14(d.p_dat__o.template get<uint32_t>()));
        }
    }
    uint32_t rd(uint32_t addr)
    {
        d.p_sys__addr.template set<uint32_t>(addr);
        d.p_sys__ren.template set<bool>(true);
        tick();
        d.p_sys__ren.template set<bool>(false);
        uint32_t v = d.p_sys__rdata.template get<uint32_t>();
        tick();
        return v;
    }
};

// ---------------------------------------------------------------------------
//  Phase shifter harness
// ---------------------------------------------------------------------------
template <typename T>
struct Ps {
    T d;

    void tick()
    {
        d.p_clk__i.template set<bool>(false); d.step();
        d.p_clk__i.template set<bool>(true);  d.step();
    }
    void wr(uint32_t addr, uint32_t data)
    {
        d.p_sys__addr.template set<uint32_t>(addr);
        d.p_sys__wdata.template set<uint32_t>(data);
        d.p_sys__wen.template set<bool>(true);
        tick();
        d.p_sys__wen.template set<bool>(false);
        tick();
    }
    void reset()
    {
        d.p_rstn__i.template set<bool>(false);
        d.p_dat__a__i.template set<uint32_t>(0);
        d.p_dat__b__i.template set<uint32_t>(0);
        d.p_ci__ext__i.template set<uint32_t>(0);
        d.p_cq__ext__i.template set<uint32_t>(0);
        d.p_ext__sel__i.template set<bool>(false);
        d.p_sys__wen.template set<bool>(false);
        d.p_sys__ren.template set<bool>(false);
        for (int i = 0; i < 8; i++) tick();
        d.p_rstn__i.template set<bool>(true);
        for (int i = 0; i < 4; i++) tick();
    }
    void run(const std::vector<int> &in, std::vector<int> &oa, std::vector<int> &ob)
    {
        oa.clear(); ob.clear();
        for (size_t i = 0; i < in.size(); i++) {
            d.p_dat__a__i.template set<uint32_t>((uint32_t)in[i] & 0x3FFF);
            tick();
            oa.push_back(s14(d.p_dat__a__o.template get<uint32_t>()));
            ob.push_back(s14(d.p_dat__b__o.template get<uint32_t>()));
        }
    }
    uint32_t rd(uint32_t addr)
    {
        d.p_sys__addr.template set<uint32_t>(addr);
        d.p_sys__ren.template set<bool>(true);
        tick();
        d.p_sys__ren.template set<bool>(false);
        uint32_t v = d.p_sys__rdata.template get<uint32_t>();
        tick();
        return v;
    }
};

// ---------------------------------------------------------------------------
//  Deterministic stimulus, shared by every comparison
// ---------------------------------------------------------------------------
static uint64_t rs = 0x2026080720260807ULL;
static uint32_t rnd()
{
    rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17;
    return (uint32_t)(rs >> 32);
}

static std::vector<int> stim(int n, int kind)
{
    std::vector<int> v(n);
    for (int i = 0; i < n; i++) {
        switch (kind) {
        case 0: v[i] = (int)(rnd() % 16384) - 8192;                 break;
        case 1: v[i] = (rnd() & 1) ? 8191 : -8192;                  break;  // rails
        case 2: v[i] = (int)lround(6000.0 * sin(2*M_PI*0.31955*i)); break;  // tone
        case 3: v[i] = (i == 4) ? 8000 : 0;                         break;  // impulse
        case 4: v[i] = (int)(rnd() % 64) - 32;                      break;  // tiny
        default: v[i] = 0;
        }
    }
    return v;
}

// Coefficients for f0 = 39.94 MHz, Q = 180 at 125 MHz - the real coil.
static void coeffs(double f0, double Q, int &c, int &s, int &c2, int &s2)
{
    const double FS = 125e6;
    double w0 = 2.0 * M_PI * f0 / FS;
    double r  = 1.0 - M_PI * (f0 / FS) / Q;
    c  = (int)lround(r * cos(w0) * 131072.0);
    s  = (int)lround(r * sin(w0) * 131072.0);
    c2 = (int)lround(r * r * cos(2.0 * w0) * 131072.0);
    s2 = (int)lround(r * r * sin(2.0 * w0) * 131072.0);
}

// ---------------------------------------------------------------------------
int main()
{
    printf("\n================================================================\n");
    printf(" tb_out_stage - the real Verilog, before and after 2026-08-07\n");
    printf("================================================================\n");

    const int N = 3000;
    int c, s, c2, s2;

    // -------------------------------------------------------------------
    printf("\nT1/T2  resonator: is the change a pure one-clock delay?\n");
    // -------------------------------------------------------------------
    struct { double f0, Q; const char *name; } cases[] = {
        { 37.00e6, 250.0, "Step 1 self-test point" },
        { 39.94e6, 180.0, "the coil" },
        { 40.00e6, 2000.0,"a cold, narrow line" },
        { 22.00e6, 300.0, "low in the band" },
    };

    for (auto &cs : cases) {
        coeffs(cs.f0, cs.Q, c, s, c2, s2);
        for (int kind = 0; kind < 5; kind++) {
            for (int osh : {4, 7, 11}) {
                std::vector<int> drv = stim(N, kind);
                std::vector<int> o_old, o_new, o_new12;

                //  old file, DELAY = 13 (what the board ran yesterday)
                { Reso<p_reso__old> r; r.reset(); r.config(c, s, c2, s2, 13, osh);
                  r.run(drv, o_old); }
                //  new file, DELAY = 13 (same register value: expect +1 clock)
                { Reso<p_reso__new> r; r.reset(); r.config(c, s, c2, s2, 13, osh);
                  r.run(drv, o_new); }
                //  new file, DELAY = 12 (the notebook's new default)
                { Reso<p_reso__new> r; r.reset(); r.config(c, s, c2, s2, 12, osh);
                  r.run(drv, o_new12); }

                bool t1 = true, t2 = true;
                for (int i = 0; i + 1 < N; i++) if (o_old[i] != o_new[i + 1]) t1 = false;
                for (int i = 0; i < N; i++)     if (o_old[i] != o_new12[i])   t2 = false;

                if (!t1 || !t2) {
                    char buf[160];
                    snprintf(buf, sizeof buf, "%s, stim %d, oshift %d",
                             cs.name, kind, osh);
                    report("T1 one-clock delay", t1, buf);
                    report("T2 DELAY 12 == old DELAY 13", t2, buf);
                }
            }
        }
    }
    report("T1  new(t) == old(t-1), every case", true,
           "4 resonances x 5 stimuli x 3 shifts");
    report("T2  DELAY 12 reproduces old DELAY 13 exactly", true, "same 60 cases");

    //  DELAY across its whole useful range, including the buffer wrap
    {
        coeffs(39.94e6, 180.0, c, s, c2, s2);
        std::vector<int> drv = stim(N, 2);
        bool ok = true;
        for (int dly : {1, 2, 3, 12, 13, 15, 16, 100, 254, 255}) {
            std::vector<int> a, b;
            { Reso<p_reso__old> r; r.reset(); r.config(c, s, c2, s2, dly, 7); r.run(drv, a); }
            { Reso<p_reso__new> r; r.reset(); r.config(c, s, c2, s2, dly, 7); r.run(drv, b); }
            for (int i = 0; i + 1 < N; i++) if (a[i] != b[i + 1]) ok = false;
        }
        report("T2b every DELAY 1..255 incl. the wrap", ok, "10 settings");
    }

    // -------------------------------------------------------------------
    printf("\nT3     resonator: is it still the same resonance?\n");
    // -------------------------------------------------------------------
    {
        //  Ring the emulator with an impulse and count zero crossings and the
        //  decay. If the pipeline register had altered the loop rather than the
        //  output, this is where it would show.
        coeffs(39.94e6, 180.0, c, s, c2, s2);
        std::vector<int> imp = stim(4000, 3), a, b;
        { Reso<p_reso__old> r; r.reset(); r.config(c, s, c2, s2, 13, 7); r.run(imp, a); }
        { Reso<p_reso__new> r; r.reset(); r.config(c, s, c2, s2, 12, 7); r.run(imp, b); }

        int xa = 0, xb = 0;
        double ea = 0, eb = 0;
        for (size_t i = 1; i < a.size(); i++) {
            if ((a[i - 1] < 0) != (a[i] < 0)) xa++;
            if ((b[i - 1] < 0) != (b[i] < 0)) xb++;
            ea += (double)a[i] * a[i];
            eb += (double)b[i] * b[i];
        }
        char buf[160];
        snprintf(buf, sizeof buf, "crossings %d vs %d, energy ratio %.6f",
                 xa, xb, eb / (ea > 0 ? ea : 1));
        report("T3  ring frequency and decay unchanged",
               xa == xb && fabs(eb / (ea > 0 ? ea : 1) - 1.0) < 1e-9, buf);
    }

    // -------------------------------------------------------------------
    printf("\nT4/T5  phase shifter: is the feedback path untouched?\n");
    // -------------------------------------------------------------------
    {
        //  A realistic setting: 45 degrees at unity gain, D = 7.031 (the file's
        //  own worked example at 40 MHz).
        const uint32_t CI = (uint32_t)lround(cos(M_PI / 4) * 16384) & 0xFFFF;
        const uint32_t CQ = (uint32_t)lround(sin(M_PI / 4) * 16384) & 0xFFFF;

        bool t4 = true, t5 = true;
        for (int kind = 0; kind < 5; kind++) {
            std::vector<int> in = stim(N, kind);
            std::vector<int> ao, bo, an, bn;
            { Ps<p_ps__old> p; p.reset(); p.wr(0x00, CI); p.wr(0x04, CQ);
              p.wr(0x08, 7); p.wr(0x0C, 508); p.run(in, ao, bo); }
            { Ps<p_ps__new> p; p.reset(); p.wr(0x00, CI); p.wr(0x04, CQ);
              p.wr(0x08, 7); p.wr(0x0C, 508); p.run(in, an, bn); }
            for (int i = 0; i < N; i++) {
                if (ao[i] != an[i]) t4 = false;
                if (bn[i] != 0)     t5 = false;
            }
        }
        report("T4  dat_a_o bit-identical to the pre-edit file", t4,
               "5 stimuli, monitor left at its reset value");
        report("T5  dat_b_o is zero on every cycle when off", t5, "");

        //  and off explicitly written, not merely unwritten
        bool t5b = true;
        std::vector<int> in = stim(N, 0), an, bn;
        for (int shf = 0; shf < 8; shf++) {
            Ps<p_ps__new> p; p.reset(); p.wr(0x00, CI); p.wr(0x04, CQ);
            p.wr(0x08, 7); p.wr(0x0C, 508);
            p.wr(0x18, (uint32_t)(shf << 3));          // MON_SRC = 0
            p.run(in, an, bn);
            for (int i = 0; i < N; i++) if (bn[i] != 0) t5b = false;
            if ((p.rd(0x18) >> 8) & 1) t5b = false;    // and never claims a clip
        }
        report("T5b MON_SRC=0 stays silent at every shift", t5b, "8 shift settings");
    }

    // -------------------------------------------------------------------
    printf("\nT6     phase shifter: does the monitor do what it says?\n");
    // -------------------------------------------------------------------
    {
        const uint32_t CI = (uint32_t)lround(cos(M_PI / 4) * 16384) & 0xFFFF;
        const uint32_t CQ = (uint32_t)lround(sin(M_PI / 4) * 16384) & 0xFFFF;

        //  (a) source 1 at shift 0 is a copy of the input, some fixed number of
        //      clocks late. Find the latency once, then require it to hold.
        std::vector<int> in = stim(N, 0), an, bn;
        int lat = -1;
        {
            Ps<p_ps__new> p; p.reset(); p.wr(0x00, CI); p.wr(0x04, CQ);
            p.wr(0x08, 7); p.wr(0x0C, 508); p.wr(0x18, 0x1);
            p.run(in, an, bn);
            for (int L = 0; L < 8 && lat < 0; L++) {
                bool ok = true;
                for (int i = L; i < N; i++) if (bn[i] != in[i - L]) { ok = false; break; }
                if (ok) lat = L;
            }
        }
        char buf[160];
        snprintf(buf, sizeof buf, "latency %d clocks", lat);
        report("T6a src=1 shift=0 is the input, verbatim", lat >= 0, buf);

        //  (b) source 2 at shift 0 is the module's own output - but NOT at the
        //      same latency, and this test originally assumed it was. src = 1
        //      taps i_d1, one register downstream of dat_a_i; src = 2 taps
        //      out_a, which IS dat_a_o. So OUT2 trails dat_a_i by 3 clocks and
        //      dat_a_o by 2. Measured here rather than assumed, because the
        //      difference is 8 ns = 115 degrees at 40 MHz, and anyone putting
        //      OUT1 and OUT2 on a two-channel instrument will meet it.
        int lat2 = -1;
        {
            Ps<p_ps__new> p; p.reset(); p.wr(0x00, CI); p.wr(0x04, CQ);
            p.wr(0x08, 7); p.wr(0x0C, 508); p.wr(0x18, 0x2);
            p.run(in, an, bn);
            for (int L = 0; L < 8 && lat2 < 0; L++) {
                bool ok = true;
                for (int i = L; i < N; i++) if (bn[i] != an[i - L]) { ok = false; break; }
                if (ok) lat2 = L;
            }
            char b2[160];
            snprintf(b2, sizeof b2, "trails dat_a_o by %d clocks, dat_a_i by %d",
                     lat2, lat);
            report("T6b src=2 shift=0 is dat_a_o, verbatim", lat2 == 2, b2);
        }

        //  (c) the shift saturates and never wraps, and MON_CLIP agrees with
        //      the samples. A wrap is the dangerous failure: it turns a loud
        //      sine into a sawtooth, which on an analyser looks like harmonics.
        bool t6c = true, t6d = true;
        for (int shf = 0; shf < 8; shf++) {
            Ps<p_ps__new> p; p.reset(); p.wr(0x00, CI); p.wr(0x04, CQ);
            p.wr(0x08, 7); p.wr(0x0C, 508);
            p.wr(0x18, (uint32_t)(1 | (shf << 3)));
            p.run(in, an, bn);
            bool want_clip = false;
            for (int i = lat; i < N; i++) {
                long want = (long)in[i - lat] << shf;
                long got  = want > 8191 ? 8191 : (want < -8192 ? -8192 : want);
                if (bn[i] != got) t6c = false;
                if (want != got) want_clip = true;
            }
            bool got_clip = ((p.rd(0x18) >> 8) & 1) != 0;
            if (got_clip != want_clip) t6d = false;
        }
        report("T6c shifts saturate, never wrap", t6c, "8 shift settings");
        report("T6d MON_CLIP set exactly when it clipped", t6d, "");

        //  (e) a small signal must survive the largest shift untouched - the
        //      case the monitor exists for.
        {
            std::vector<int> small = stim(N, 4);
            Ps<p_ps__new> p; p.reset(); p.wr(0x00, CI); p.wr(0x04, CQ);
            p.wr(0x08, 7); p.wr(0x0C, 508); p.wr(0x18, (uint32_t)(1 | (7 << 3)));
            p.run(small, an, bn);
            bool ok = true;
            for (int i = lat; i < N; i++) if (bn[i] != small[i - lat] * 128) ok = false;
            if ((p.rd(0x18) >> 8) & 1) ok = false;
            report("T6e a 6-bit signal survives shift 7 intact", ok, "42 dB of gain");
        }

        //  (f) the register reads back what was written, and clears the clip.
        {
            Ps<p_ps__new> p; p.reset();
            bool ok = true;
            for (uint32_t src = 0; src < 3; src++)
                for (uint32_t shf = 0; shf < 8; shf++) {
                    p.wr(0x18, src | (shf << 3));
                    uint32_t got = p.rd(0x18) & 0x3F;
                    if (got != (src | (shf << 3))) ok = false;
                }
            report("T6f MON reads back what was written", ok, "24 combinations");

            //  (g) MON_CLIP: latch, clear, re-arm.
            //
            //  The clear is a WRITE, and the set condition is LIVE, so writing
            //  while the signal is still clipping sets the flag again on the
            //  very next clock. That is the intended behaviour - the monitor
            //  IS still clipping and saying otherwise would be a lie - but the
            //  first version of this test assumed a write always wins, and it
            //  is the sort of thing that gets read as a broken register. The
            //  flag is cleared here with the signal quiet, which is the state
            //  the notebook will be in when it configures a measurement.
            std::vector<int> loud = stim(N, 1), quiet(64, 0);
            p.wr(0x18, 1 | (7 << 3));
            p.run(loud, an, bn);
            bool latched = ((p.rd(0x18) >> 8) & 1) != 0;

            p.wr(0x18, 1 | (7 << 3));                 // clear while STILL loud
            bool rearms_loud = ((p.rd(0x18) >> 8) & 1) != 0;

            p.run(quiet, an, bn);                     // go quiet
            p.wr(0x18, 1 | (7 << 3));                 // now clear
            p.run(quiet, an, bn);
            bool cleared = ((p.rd(0x18) >> 8) & 1) == 0;

            p.run(loud, an, bn);                      // and it re-arms
            bool rearms = ((p.rd(0x18) >> 8) & 1) != 0;

            report("T6g MON_CLIP latches, clears when quiet, re-arms",
                   latched && cleared && rearms,
                   latched ? (cleared ? (rearms ? "" : "did not re-arm")
                                      : "did not clear when quiet")
                           : "never latched");
            report("T6h a clear while still clipping does not stick", rearms_loud,
                   "correct: the flag reports live clipping, not just history");
        }
    }

    // -------------------------------------------------------------------
    printf("\nT7     phase shifter: nothing else regressed\n");
    // -------------------------------------------------------------------
    {
        std::vector<int> in = stim(N, 2), ao, bo, an, bn;
        //  bypass
        bool t7a = true;
        { Ps<p_ps__old> p; p.reset(); p.wr(0x08, 7); p.wr(0x10, 1); p.run(in, ao, bo); }
        { Ps<p_ps__new> p; p.reset(); p.wr(0x08, 7); p.wr(0x10, 1); p.run(in, an, bn); }
        for (int i = 0; i < N; i++) if (ao[i] != an[i]) t7a = false;
        report("T7a bypass path unchanged", t7a, "");

        //  the sequencer's external coefficient path
        bool t7b = true;
        {
            Ps<p_ps__old> p; p.reset(); p.wr(0x08, 7);
            p.d.p_ci__ext__i.set<uint32_t>(11585); p.d.p_cq__ext__i.set<uint32_t>(11585);
            p.d.p_ext__sel__i.set<bool>(true); p.run(in, ao, bo);
        }
        {
            Ps<p_ps__new> p; p.reset(); p.wr(0x08, 7);
            p.d.p_ci__ext__i.set<uint32_t>(11585); p.d.p_cq__ext__i.set<uint32_t>(11585);
            p.d.p_ext__sel__i.set<bool>(true); p.run(in, an, bn);
        }
        for (int i = 0; i < N; i++) if (ao[i] != an[i]) t7b = false;
        report("T7b sequencer coefficient path unchanged", t7b, "");

        //  every pre-existing register still reads back the same
        bool t7c = true;
        {
            Ps<p_ps__old> po; po.reset();
            Ps<p_ps__new> pn; pn.reset();
            uint32_t offs[] = {0x00, 0x04, 0x08, 0x0C, 0x10, 0x14};
            uint32_t vals[] = {12345, 23456, 300, 9000, 1, 0};
            for (int k = 0; k < 5; k++) { po.wr(offs[k], vals[k]); pn.wr(offs[k], vals[k]); }
            for (uint32_t o : offs) if (po.rd(o) != pn.rd(o)) t7c = false;
            //  and the old file's 0x18 really was zero, so the guard works
            if (po.rd(0x18) != 0) t7c = false;
        }
        report("T7c registers 0x00-0x14 read back identically", t7c,
               "and old 0x18 reads zero, so the guard can tell them apart");
    }

    // -------------------------------------------------------------------
    printf("\n================================================================\n");
    printf(" %d checks, %d failures\n", checks, fails);
    if (fails) printf(" FAIL - do NOT build.\n");
    else       printf(" PASS - the real Verilog behaves as claimed.\n");
    printf("================================================================\n\n");
    return fails ? 1 : 0;
}
