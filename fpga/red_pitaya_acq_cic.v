/**
 * @brief Cascaded integrator-comb (CIC) decimating filter for the acquisition
 *        system.  One channel; instantiate twice (once for I, once for Q).
 *
 * Project-specific acquisition module.
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * Part of the acquisition system of Herkenhoff et al., Rev. Sci. Instrum. 92,
 * 103201 (2021).  Fig. 6a, the two blocks labelled "CIC".
 *
 * ===========================================================================
 *  PLAIN-ENGLISH SUMMARY: WHAT THIS BLOCK IS AND WHY IT EXISTS
 * ===========================================================================
 *  The board takes 125 million measurements per second.  The thing we actually
 *  want to see is a feature a few kilohertz wide.  Recording everything would
 *  mean storing 125 million numbers per second to look at something that only
 *  needs a few thousand - a waste of memory, of bus bandwidth, and of the
 *  processor's time.
 *
 *  So we AVERAGE.  Take R consecutive samples, average them, keep one number,
 *  throw the rest away.  Do that continuously and the data rate drops by a
 *  factor of R.  Averaging also suppresses noise: random noise partly cancels
 *  when you add samples together, while a steady signal does not.  Averaging
 *  R samples improves the signal-to-noise ratio by a factor of sqrt(R), so
 *  R = 4096 buys a factor of 64 - about 36 dB.  That improvement is the entire
 *  reason this block is here.
 *
 *  "Throwing samples away" is called DECIMATION, and R is the decimation
 *  factor.  This module supports R = 64, 128, 256, ... up to 4096, exactly the
 *  range in the paper, selected at run time from the Jupyter notebook.
 *
 *  A CIC filter is simply a very efficient way to do that averaging - one that
 *  uses NO MULTIPLIERS AT ALL, only additions and subtractions.  That matters
 *  because multipliers are a scarce resource on this chip (80 of them) and the
 *  correction filter later in the chain needs most of them.
 *
 * ===========================================================================
 *  HOW A CIC FILTER WORKS - the trick, in three steps
 * ===========================================================================
 *  Suppose you want a running total of the last R samples.  The naive way is
 *  to keep the last R samples and add them all up every clock cycle: R
 *  additions per sample, and R = 4096 would be hopeless.
 *
 *  The trick: a running total of the last R samples equals
 *
 *      (total of EVERYTHING so far)  -  (total of everything up to R samples ago)
 *
 *  Both of those running totals come from the same accumulator, just read at
 *  different times.  So the whole job is:
 *
 *    STEP 1  INTEGRATOR - one accumulator that adds every incoming sample to a
 *            running total, forever.  One addition per clock.  ("Integrator"
 *            because a running total is discrete integration.)
 *
 *    STEP 2  DOWNSAMPLE - only look at that total once every R clocks.
 *
 *    STEP 3  COMB - subtract the previous value we looked at from the current
 *            one.  The difference is the sum of everything that arrived in
 *            between: exactly the block of R samples we wanted.  ("Comb"
 *            because subtracting a delayed copy gives a comb-shaped frequency
 *            response, with regularly spaced notches.)
 *
 *  Total cost: one addition and one subtraction per sample, whatever R is.
 *  That is why this structure is used everywhere in radio hardware.
 *
 *  Doing it once gives a plain box-car average, which is a fairly poor filter -
 *  it lets too much through at frequencies we want rejected.  Chaining
 *  NSTAGE copies of the integrator (before the downsampler) and NSTAGE copies
 *  of the comb (after it) sharpens the response considerably.  NSTAGE = 4 here.
 *
 * ===========================================================================
 *  THE OVERFLOW THAT IS NOT A BUG
 * ===========================================================================
 *  The integrators add up every sample forever, so their totals grow without
 *  limit and WILL overflow - the counter runs off the top and wraps back round
 *  to the bottom, like a car odometer rolling over.
 *
 *  This is deliberate and it is safe.  Hogenauer's 1981 result is that if you
 *  use ordinary two's-complement wraparound arithmetic and make the registers
 *  wide enough, the comb's subtraction UNDOES the wraparound exactly.  Rolling
 *  over and then subtracting gives the same answer as never rolling over at
 *  all, because the wrap cancels in the difference.
 *
 *  "Wide enough" means:
 *
 *      WACC  >=  DWI  +  NSTAGE * log2(R_max)
 *            =    24  +  4 * 12  =  72 bits
 *
 *  Hence the 72-bit registers below.  Do not narrow them without redoing that
 *  sum, and note it depends on the LARGEST decimation you allow, not the one
 *  currently selected.
 *
 * ===========================================================================
 *  OUTPUT SCALING - why the output slice moves with the decimation factor
 * ===========================================================================
 *  A CIC does not average, it SUMS.  Summing R samples makes the numbers R
 *  times bigger, and with NSTAGE stages the growth is R^NSTAGE.  For R = 4096
 *  and NSTAGE = 4 that is 2^48 - the answer is 48 bits further up the register
 *  than the input was.  To turn the sum back into an average we divide by
 *  R^NSTAGE, and because R is restricted to powers of two that division is
 *  just "read the bits higher up", which costs no hardware at all.
 *
 *  (This is the only reason R is restricted to powers of two.  Arbitrary R
 *  would need a real divider.  Powers of two from 64 to 4096 give a perfectly
 *  useful set of measurement windows, so the restriction costs nothing.)
 *
 *  We take a 32-bit slice positioned so that the output is on the SAME scale
 *  as the 24-bit input, plus 8 extra bits below the input's least significant
 *  bit.  Those 8 bits are real, earned resolution - averaging 4096 samples
 *  genuinely resolves detail 6 bits finer than a single sample can.  Keeping
 *  8 bits means none of it is thrown away.  24 + 8 = 32, which is the datapath
 *  width the paper specifies after the CIC filters.
 *
 * ===========================================================================
 *  USAGE NOTE
 * ===========================================================================
 *  Do not change set_dec_log2_i while data is flowing.  The integrators hold a
 *  running total that assumes a fixed R; changing R mid-stream leaves a
 *  meaningless partial sum in the pipeline and produces a burst of garbage.
 *  The host should stop acquisition, change the setting, then pulse the reset.
 *  The parent module (red_pitaya_acq) enforces this.
 */

`timescale 1ns / 1ps

module red_pitaya_acq_cic #(
  parameter integer DWI      = 24,   // input width, signed (from the mixer)
  parameter integer DWO      = 32,   // output width, signed (to the FIR filter)
  parameter integer NSTAGE   = 4,    // number of integrator/comb stages
  parameter integer LMAX     = 12,   // largest supported log2(R), i.e. R = 4096
  parameter integer WACC     = DWI + NSTAGE*LMAX   // = 72, see overflow note above
)(
  // ---- clock and reset ----
  input                          clk_i         ,  //!< 125 MHz processing clock
  input                          rstn_i        ,  //!< active-LOW synchronous reset

  // ---- control ----
  input      [ 4-1: 0]           set_dec_log2_i,  //!< log2(R): 6 => R=64 ... 12 => R=4096
  input                          stb_i         ,  //!< 1 clock high every R clocks (from parent)

  // ---- data ----
  input      signed [ DWI-1: 0]  dat_i         ,  //!< input sample, every clock
  output reg signed [ DWO-1: 0]  dat_o         ,  //!< decimated output sample
  output                         stb_o            //!< 1 clock high when dat_o is fresh
);

//---------------------------------------------------------------------------------
//  SECTION 1 - INTEGRATORS  (run at the full 125 MHz rate)
//
//  integ[0] accumulates the input; integ[1] accumulates integ[0]; and so on.
//  Each is a plain "add to running total" register.  They are allowed - in fact
//  required - to overflow; see the overflow note in the header.
//
//  The input is sign-extended to the full accumulator width first.  Sign
//  extension means copying the sign bit leftwards, which is how a negative
//  number keeps its value when widened.  Zero-padding instead would turn every
//  negative sample into a huge positive one.
//---------------------------------------------------------------------------------
wire signed [ WACC-1: 0] dat_ext = {{(WACC-DWI){dat_i[DWI-1]}}, dat_i};

reg signed [ WACC-1: 0] integ [0:NSTAGE-1];

integer i;
always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    for (i = 0; i < NSTAGE; i = i + 1)
      integ[i] <= {WACC{1'b0}};
  end else begin
    integ[0] <= integ[0] + dat_ext;            // first stage sums the input
    for (i = 1; i < NSTAGE; i = i + 1)
      integ[i] <= integ[i] + integ[i-1];       // each later stage sums the one before
  end
end

//---------------------------------------------------------------------------------
//  SECTION 2 - STROBE PIPELINE
//
//  Everything after this point runs at the SLOW rate: one sample every R clocks.
//  Rather than do all NSTAGE subtractions in a single clock cycle - which would
//  chain four 72-bit subtractors back to back and comfortably miss the 8 ns
//  clock period - we give each comb stage its own clock cycle.
//
//  We can afford to, because the next sample is at least 64 clocks away.  This
//  shift register simply carries the strobe along, one stage per clock, so comb
//  stage k fires on stb_pipe[k], one clock later than stage k-1.
//
//  Note stb_pipe[0] is stb_i delayed by one clock, so the whole comb section
//  runs one clock behind the incoming strobe. That is a constant offset applied
//  identically to every sample and to both the I and Q channels, so it has no
//  effect on the measurement.
//---------------------------------------------------------------------------------
//  The register is NSTAGE+2 bits wide, not NSTAGE+1. Bits 0..NSTAGE-1 fire the
//  comb stages; bit NSTAGE fires the output register; bit NSTAGE+1 is the
//  "output is now valid" flag. See the note on stb_o at the bottom of the file
//  for why that last bit is needed.
//---------------------------------------------------------------------------------
reg [ NSTAGE+1: 0] stb_pipe;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) stb_pipe <= {(NSTAGE+2){1'b0}};
  else                stb_pipe <= {stb_pipe[NSTAGE:0], stb_i};
end

//---------------------------------------------------------------------------------
//  SECTION 3 - COMBS  (run at the decimated rate)
//
//  Each stage computes  out = in - (the value of in one decimated sample ago).
//  comb_prev[k] holds that previous value.
//
//  Stage 0 takes its input from the last integrator, sampled at the instant its
//  strobe arrives.  That sampling IS the downsampling step - there is no
//  separate hardware for it.  Everything else only ever runs on a strobe, so
//  the fast side of the filter is just the four accumulators above.
//---------------------------------------------------------------------------------
reg  signed [ WACC-1: 0] comb_prev [0:NSTAGE-1];  // previous input to each stage
reg  signed [ WACC-1: 0] comb_out  [0:NSTAGE-1];  // output of each stage
wire signed [ WACC-1: 0] stage_in  [0:NSTAGE-1];  // what each stage is fed

genvar g;
generate
  for (g = 0; g < NSTAGE; g = g + 1) begin: comb_stage

    // Wire up this stage's input: the last integrator for stage 0, otherwise
    // the output of the stage before.  Because stage g fires one clock later
    // than stage g-1, that previous output has already settled by the time we
    // read it - which is the whole point of spreading the stages over separate
    // clock cycles.
    if (g == 0) begin: from_integrator
      assign stage_in[g] = integ[NSTAGE-1];
    end else begin: from_previous_comb
      assign stage_in[g] = comb_out[g-1];
    end

    always @(posedge clk_i) begin
      if (rstn_i == 1'b0) begin
        comb_prev[g] <= {WACC{1'b0}};
        comb_out [g] <= {WACC{1'b0}};
      end else if (stb_pipe[g]) begin
        comb_prev[g] <= stage_in[g];                  // remember for next time
        comb_out [g] <= stage_in[g] - comb_prev[g];   // difference = the block sum
      end
    end

  end
endgenerate

//---------------------------------------------------------------------------------
//  SECTION 4 - OUTPUT SCALING
//
//  Pick the 32-bit window of the 72-bit result that corresponds to dividing by
//  R^NSTAGE and keeping 8 fractional bits (see the scaling note in the header).
//
//  The window starts at bit  NSTAGE*log2(R) - 8.  Written out for NSTAGE = 4:
//
//      R =   64 (log2 =  6)  ->  start at bit 16  ->  bits [47:16]
//      R =  128 (log2 =  7)  ->  start at bit 20  ->  bits [51:20]
//      R =  256 (log2 =  8)  ->  start at bit 24  ->  bits [55:24]
//      R =  512 (log2 =  9)  ->  start at bit 28  ->  bits [59:28]
//      R = 1024 (log2 = 10)  ->  start at bit 32  ->  bits [63:32]
//      R = 2048 (log2 = 11)  ->  start at bit 36  ->  bits [67:36]
//      R = 4096 (log2 = 12)  ->  start at bit 40  ->  bits [71:40]
//
//  FIX: the window position is now COMPUTED from the parameters rather than
//  written out as a hard-coded table of bit ranges. The table above was correct
//  only for DWI=24, DWO=32, NSTAGE=4; changing any parameter would have left it
//  silently selecting the wrong bits, which is exactly the kind of fault that
//  produces plausible-looking but wrong data. The comment table is kept because
//  it is genuinely useful to read, but the hardware no longer depends on it.
//
//  `dec_clamped` guards the arithmetic: an out-of-range setting falls back to
//  the minimum decimation rather than indexing off the end of the register.
//  The host should never write one; this is a safety net.
//
//  `[base +: DWO]` is Verilog-2001 indexed part-select: "DWO bits starting at
//  bit `base`, counting upwards". The base may be a variable, which a plain
//  [msb:lsb] range may not. It builds a small multiplexer - only 7 possible
//  values of `base` exist.
//
//  No overflow check is needed: by construction the window covers the full
//  range the result can occupy, no more and no less.
//---------------------------------------------------------------------------------
localparam integer LMIN = 6;   // smallest supported log2(R), i.e. R = 64

wire [3:0] dec_clamped = (set_dec_log2_i < LMIN[3:0]) ? LMIN[3:0] :
                         (set_dec_log2_i > LMAX[3:0]) ? LMAX[3:0] : set_dec_log2_i;

// Bottom bit of the output window = NSTAGE*log2(R) - (DWO - DWI).
wire [7:0] out_base = NSTAGE[7:0] * dec_clamped - (DWO[7:0] - DWI[7:0]);

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) dat_o <= {DWO{1'b0}};
  else if (stb_pipe[NSTAGE]) dat_o <= comb_out[NSTAGE-1][out_base +: DWO];
end

//---------------------------------------------------------------------------------
//  Output valid strobe.
//
//  FIX (off-by-one): this used to be stb_pipe[NSTAGE], which is asserted on the
//  SAME clock edge that writes dat_o. A consumer sampling on that strobe would
//  therefore have captured the PREVIOUS decimated sample - every sample shifted
//  by one, silently. dat_o only becomes readable on the following clock, so the
//  valid flag has to be one stage further down the pipeline.
//
//  Timeline for stb_i arriving at clock 0, NSTAGE = 4:
//     clock 1 : stb_pipe[0] -> comb stage 0 computes
//     clock 2 : stb_pipe[1] -> comb stage 1 computes
//     clock 3 : stb_pipe[2] -> comb stage 2 computes
//     clock 4 : stb_pipe[3] -> comb stage 3 computes
//     clock 5 : stb_pipe[4] -> dat_o is written
//     clock 6 : stb_pipe[5] -> dat_o is stable and readable  <- stb_o here
//
//  There is no risk of these overlapping: the next stb_i is at least 64 clocks
//  away, and the pipeline is only NSTAGE+2 = 6 deep.
//---------------------------------------------------------------------------------
assign stb_o = stb_pipe[NSTAGE+1];

endmodule
