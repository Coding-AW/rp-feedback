// ===========================================================================
//  tb_dac_sum.cc - exhaustive check of the top level's OUT2 summation leg.
//
//  Sweeps every one of the 16384 values the monitor can present, with the
//  generator silent, and asserts:
//
//    D1  CH B is monotonic in the signed monitor sample. A signedness fault
//        shows here immediately: negative samples would fold to the positive
//        rail and monotonicity would break in the middle.
//    D2  CH B reproduces the sample exactly - the generator is off, so the
//        sum is the identity and nothing should be lost or saturated.
//    D3  CH B behaves IDENTICALLY to CH A given the same input. CH A is the
//        working, characterised feedback output; if the two agree then the
//        monitor inherits a path that is known good on real hardware, which
//        is a stronger statement than any reading of the language reference.
//    D4  the saturation still works when the generator IS running, over all
//        16384 x 16384 combinations reduced to a representative sweep,
//        including both rails.
// ===========================================================================
#include <cstdio>
#include <cstdint>
#include "tb_dac_sum_rtl.h"

using namespace cxxrtl_design;

static int fails = 0, checks = 0;
static void report(const char *name, bool ok, const char *detail = "")
{
    checks++; if (!ok) fails++;
    printf("  %-4s %-56s %s\n", ok ? "PASS" : "FAIL", name, detail);
}

static int s14(uint32_t v) { return (v & 0x2000u) ? (int)v - 0x4000 : (int)v; }

struct Dut {
    p_tb__dac__sum d;
    void set(int pid_b, int asg_b, int pid_a, int asg_a)
    {
        d.p_pid__b__i.set<uint32_t>((uint32_t)pid_b & 0x3FFF);
        d.p_asg__b__i.set<uint32_t>((uint32_t)asg_b & 0x3FFF);
        d.p_pid__a__i.set<uint32_t>((uint32_t)pid_a & 0x3FFF);
        d.p_asg__a__i.set<uint32_t>((uint32_t)asg_a & 0x3FFF);
        d.step();
    }
    int dac_b() { return s14(d.p_dac__b__o.get<uint32_t>()); }
    int dac_a() { return s14(d.p_dac__a__o.get<uint32_t>()); }
    uint32_t raw_b() { return d.p_dac__dat__b__o.get<uint32_t>(); }
    uint32_t raw_a() { return d.p_dac__dat__a__o.get<uint32_t>(); }
};

int main()
{
    printf("\n================================================================\n");
    printf(" tb_dac_sum - the OUT2 leg of red_pitaya_top.sv, exhaustively\n");
    printf("================================================================\n\n");

    Dut u;

    //  D1 / D2 / D3 : generator silent, sweep the whole monitor range
    //
    //  NOTE THE SLOPE. red_pitaya_top.sv converts to the DAC word with
    //      dac_dat_b <= {dac_b[13], ~dac_b[12:0]};
    //  and its own comment says "signed to unsigned (also to NEGATIVE
    //  SLOPE)". So the word runs 0x3FFF at -8192 down to 0x0000 at +8191:
    //  strictly DECREASING. That is not a fault and it is not new - OUT1 has
    //  always done it - but it means OUT2 is INVERTED with respect to the
    //  sample the monitor selected. Irrelevant to a spectrum analyser, which
    //  measures magnitude; it matters if anyone ever compares OUT1 and OUT2
    //  for phase, on top of the 2-clock offset the monitor already adds.
    //
    //  This check originally asserted an INCREASING word and failed at the
    //  second sample. Recorded because "the test asserted the wrong sign" is
    //  a cheaper explanation than any of the ones considered first.
    bool mono = true, exact = true, same = true;
    long prev_raw = -1;
    int  break_at = 0;
    for (int v = -8192; v <= 8191; v++) {
        u.set(v, 0, v, 0);
        if (u.dac_b() != v) { exact = false; }
        if (u.dac_b() != u.dac_a() || u.raw_b() != u.raw_a()) same = false;
        long raw = (long)u.raw_b();          // the word the converter sees
        if (prev_raw >= 0 && raw >= prev_raw && mono) { mono = false; break_at = v; }
        prev_raw = raw;
    }
    char buf[128];
    snprintf(buf, sizeof buf, "16384 values, strictly decreasing (inverting DAC)");
    if (!mono) snprintf(buf, sizeof buf, "monotonicity breaks at sample %d", break_at);
    report("D1 OUT2 is monotonic across the whole signed range", mono, buf);
    report("D2 OUT2 reproduces the sample exactly", exact, "generator silent");
    report("D3 CH B behaves identically to the working CH A", same,
           "same input, same DAC word, all 16384");

    //  the specific value a signedness fault would ruin
    u.set(-1, 0, -1, 0);
    snprintf(buf, sizeof buf, "-1 -> dac_b %d, DAC word 0x%04X", u.dac_b(), u.raw_b());
    report("D3b a single negative sample survives", u.dac_b() == -1, buf);
    u.set(-8192, 0, -8192, 0);
    snprintf(buf, sizeof buf, "-8192 -> dac_b %d", u.dac_b());
    report("D3c the negative rail survives", u.dac_b() == -8192, buf);

    //  D4 : saturation with the generator running too
    bool sat_ok = true;
    for (int a = -8192; a <= 8191; a += 37) {
        for (int b = -8192; b <= 8191; b += 41) {
            u.set(b, a, b, a);
            long want = (long)a + b;
            long clip = want > 8191 ? 8191 : (want < -8192 ? -8192 : want);
            if (u.dac_b() != clip) sat_ok = false;
            if (u.dac_b() != u.dac_a()) sat_ok = false;
        }
    }
    //  and both rails exactly
    int corners[][2] = {{8191, 8191}, {-8192, -8192}, {8191, -8192}, {-8192, 8191}};
    for (auto &c : corners) {
        u.set(c[0], c[1], c[0], c[1]);
        long want = (long)c[0] + c[1];
        long clip = want > 8191 ? 8191 : (want < -8192 ? -8192 : want);
        if (u.dac_b() != clip) sat_ok = false;
    }
    report("D4 monitor + generator saturates correctly", sat_ok,
           "~78k combinations plus all four corners");

    printf("\n================================================================\n");
    printf(" %d checks, %d failures\n", checks, fails);
    if (fails) printf(" FAIL - the OUT2 leg is not safe. Do NOT build.\n");
    else       printf(" PASS - pid_dat[1] is treated as signed; OUT2 is faithful.\n");
    printf("================================================================\n\n");
    return fails ? 1 : 0;
}
