/**
 * @brief Local-oscillator generator (direct digital synthesis) for the
 *        acquisition system.
 *
 * Project-specific acquisition module.
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * Part of the acquisition system of Herkenhoff et al., "A digital feedback
 * system for advanced ion manipulation techniques in Penning traps",
 * Rev. Sci. Instrum. 92, 103201 (2021).  See Fig. 6a, the block labelled
 * "Local osc." feeding the two mixer multipliers.
 *
 * ===========================================================================
 *  WHAT THIS MODULE IS FOR
 * ===========================================================================
 *  The electron signal sits at ~40 MHz, but the interesting structure (the ion
 *  dip, the resonator lineshape) is only a few kHz wide.  Recording the raw
 *  125 MSPS stream to look at a few kHz would be absurdly wasteful.
 *
 *  Instead we SHIFT the 40 MHz carrier down to 0 Hz and then throw away the
 *  now-empty bandwidth.  Shifting down is done by multiplying the input by a
 *  reference sine wave at exactly the carrier frequency - that is what this
 *  module generates.  Because a single multiplication loses the sign of the
 *  frequency offset (a signal 1 kHz above and 1 kHz below the carrier would
 *  look identical), we generate TWO references 90 degrees apart:
 *
 *      cos(2*pi*f_lo*t)   -> "in-phase"   (I) reference
 *      sin(2*pi*f_lo*t)   -> "quadrature" (Q) reference
 *
 *  Multiplying by both and keeping both results preserves the full complex
 *  information, so a signal above the carrier is distinguishable from one
 *  below it.  This is the standard "IQ" or "complex" downconversion.
 *
 * ===========================================================================
 *  HOW DIRECT DIGITAL SYNTHESIS WORKS (the whole idea in four lines)
 * ===========================================================================
 *  1. Keep a wide unsigned counter, `phase_acc`, that represents the current
 *     angle of the sine wave.  The FULL counter range 0 .. 2^PACCW-1 maps onto
 *     one full turn, 0 .. 360 degrees.  Because the counter is binary it wraps
 *     around by itself, which is exactly what an angle should do.
 *
 *  2. Every clock cycle, add a constant `set_finc` to it.  Adding a bigger
 *     constant means you get round the circle faster, i.e. a higher frequency:
 *
 *          f_out = f_clk * set_finc / 2^PACCW
 *     =>   set_finc = round( f_out / f_clk * 2^PACCW )
 *
 *     With PACCW = 32 and f_clk = 125 MHz the frequency step is
 *     125e6 / 2^32 = 0.0291 Hz - far finer than anything we need.
 *     For f_out = 40 MHz:  set_finc = round(0.32 * 2^32) = 1374389535.
 *
 *  3. Take the TOP `LUTW` bits of the counter as an address into a lookup
 *     table holding one period of a sine wave.  Only the top bits are used
 *     because the table cannot be 2^32 entries long; discarding the low bits
 *     is called "phase truncation" (see the accuracy note below).
 *
 *  4. Read the table twice at once, at addresses a quarter-turn apart, to get
 *     the sine and cosine simultaneously.  Block RAM has two independent read
 *     ports, so this costs ONE memory and no extra logic.
 *
 * ===========================================================================
 *  ACCURACY NOTE - why LUTW is a trade-off worth understanding
 * ===========================================================================
 *  Throwing away the low bits of the phase (step 3) means the output is not a
 *  perfect sine: it is a perfect sine plus small periodic error, which shows up
 *  in the spectrum as discrete spurious tones ("spurs").  The rule of thumb is
 *
 *      worst spur  ~=  -(6.02 * LUTW - 3.9)  dBc
 *
 *  LUTW = 12 -> about -68 dBc, and costs one 36 kbit block RAM tile.
 *  LUTW = 13 -> about -74 dBc, two tiles.   LUTW = 14 -> about -80 dBc, four.
 *
 *  A spur only matters if it lands inside the measurement window after
 *  downconversion, i.e. if it sits within a few kHz of the carrier.  DDS spurs
 *  are spread widely, so 12 bits is a sensible default.  If you ever see a
 *  suspicious fixed-frequency feature in an acquired spectrum, raise LUTW as a
 *  first diagnostic - it is a one-character change and costs only block RAM,
 *  of which this design has plenty spare (30 of 60 tiles free).
 *
 * ===========================================================================
 *  SYNTHESIS NOTE - how the sine table gets its contents
 * ===========================================================================
 *  The table is filled by an `initial` block that calls the real-valued system
 *  function $sin.  Vivado evaluates this at ELABORATION time (i.e. on the PC,
 *  during synthesis) and bakes the resulting constants into the block RAM
 *  initialisation.  No hardware is generated for the loop itself.
 *
 *  If a future Vivado version ever refuses this, the fallback is to generate
 *  the numbers with the supplied Python script and load them with $readmemh:
 *
 *      // initial $readmemh("lo_sine.mem", sine_rom);
 *
 *  (`tools/gen_lo_sine.py` writes that file.)  Both routes produce identical
 *  contents; the $sin version is preferred only because it keeps the table
 *  definition inside this file where it can be read and checked.
 */

`timescale 1ns / 1ps

module red_pitaya_acq_dds #(
  parameter integer PACCW = 32,   // phase accumulator width (frequency resolution)
  parameter integer LUTW  = 12,   // sine table address width -> 2^LUTW entries
  parameter integer DWO   = 16    // output word width, signed
)(
  // ---- clock and reset ----
  input                      clk_i     ,  //!< 125 MHz processing clock
  input                      rstn_i    ,  //!< active-LOW synchronous reset

  // ---- control ----
  input      [ PACCW-1: 0]   set_finc_i,  //!< frequency increment (see formula above)
  input                      phase_rst_i, //!< 1-cycle pulse: restart the sine from 0 deg

  // ---- outputs (two references, exactly 90 degrees apart) ----
  output reg signed [ DWO-1: 0] lo_cos_o ,  //!< cos(theta), the in-phase   reference
  output reg signed [ DWO-1: 0] lo_sin_o    //!< sin(theta), the quadrature reference
);

//---------------------------------------------------------------------------------
//  Derived constants
//---------------------------------------------------------------------------------
localparam integer LUT_DEPTH = 1 << LUTW;        // number of table entries, e.g. 4096
localparam integer QUARTER   = LUT_DEPTH >> 2;   // a quarter turn, in table entries
localparam real    PI        = 3.14159265358979323846;

// Peak amplitude of the stored sine.  Deliberately (2^(DWO-1) - 1), NOT 2^(DWO-1),
// so that the most negative value is -32767 rather than -32768.  A symmetric range
// means negating the reference can never overflow, which removes a whole class of
// awkward edge cases downstream.
localparam real    AMPL      = (1 << (DWO-1)) - 1;   // 32767 for DWO = 16

//---------------------------------------------------------------------------------
//  Sine lookup table - one full period, filled at elaboration time
//---------------------------------------------------------------------------------
(* rom_style = "block" *)                       // force block RAM, not logic fabric
reg signed [ DWO-1: 0] sine_rom [0:LUT_DEPTH-1];

integer k;
initial begin
  for (k = 0; k < LUT_DEPTH; k = k + 1)
    // $rtoi truncates towards zero; adding a half-LSB of the correct sign first
    // turns that into round-to-nearest, which halves the table's amplitude error.
    sine_rom[k] = $rtoi( AMPL * $sin(2.0 * PI * k / LUT_DEPTH)
                         + ( $sin(2.0 * PI * k / LUT_DEPTH) >= 0.0 ? 0.5 : -0.5 ) );
end

//---------------------------------------------------------------------------------
//  Phase accumulator - the counter that represents the current angle
//---------------------------------------------------------------------------------
reg [ PACCW-1: 0] phase_acc;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0)      phase_acc <= {PACCW{1'b0}};   // reset to 0 degrees
  else if (phase_rst_i)    phase_acc <= {PACCW{1'b0}};   // triggered restart
  else                     phase_acc <= phase_acc + set_finc_i;
  // No explicit wrap needed: the accumulator is exactly PACCW bits wide, so it
  // rolls over from 359.99... degrees back to 0 degrees on its own.
end

//---------------------------------------------------------------------------------
//  Table addresses - two reads, a quarter turn apart
//
//  Address A is the raw truncated phase              -> gives sin(theta)
//  Address B is that plus a quarter of the table     -> gives sin(theta + 90) = cos(theta)
//
//  The addition wraps naturally because both operands are LUTW bits wide.
//---------------------------------------------------------------------------------
wire [ LUTW-1: 0] addr_sin = phase_acc[PACCW-1 : PACCW-LUTW];
wire [ LUTW-1: 0] addr_cos = addr_sin + QUARTER[LUTW-1:0];

//---------------------------------------------------------------------------------
//  Registered reads.
//
//  Registering the output is what lets Vivado map this to a true dual-port block
//  RAM (block RAM reads are inherently synchronous).  It costs ONE clock cycle of
//  latency, which is harmless here: the local oscillator is a free-running
//  reference, so a fixed one-cycle delay is just a constant, calibratable phase
//  offset of 360 * f_lo / f_clk degrees - and in any case both references are
//  delayed identically, so their 90 degree relationship is exact.
//---------------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    lo_sin_o <= {DWO{1'b0}};
    lo_cos_o <= {DWO{1'b0}};
  end else begin
    lo_sin_o <= sine_rom[addr_sin];
    lo_cos_o <= sine_rom[addr_cos];
  end
end

endmodule
