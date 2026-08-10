/**
 * @brief Digital resonator - a stand-in for the trap's detection coil.
 *
 * Project-specific resonator module.
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * ===========================================================================
 *  WHAT THIS IS FOR
 * ===========================================================================
 *  The detection system's resonator is a high-Q tuned circuit. The active
 *  feedback system works by adding a phase-shifted copy of the resonator's own
 *  signal back into it, which changes how fast the resonance decays - narrowing
 *  the line at one phase and broadening it at the opposite one.
 *
 *  Testing that against the real coil means the cryostat, the trap, and a
 *  resonator whose exact centre frequency and Q are themselves things you are
 *  trying to measure. So this module IS a resonator, built in logic, with a
 *  centre frequency and a Q that software sets exactly.
 *
 *  The point is a KNOWN ANSWER. You choose Q; the sweep must return that Q. You
 *  choose the feedback gain; the linewidth must change by the amount the physics
 *  says. Anything else is the instrument, not the resonator - which is the only
 *  way to tell those two apart, and the approach that found the one real bug in
 *  the acquisition system.
 *
 *  Enabled, it replaces the digitised input to BOTH the feedback path and the
 *  acquisition system, and its own input is what the board is sending out. So
 *  the whole loop closes inside the chip with no cables:
 *
 *      generator ─┐
 *                 ├──▶ DAC value ──▶ [THIS] ──┬──▶ acquisition system
 *      feedback ──┘                           │
 *          ▲                                  │
 *          └──────────────────────────────────┘
 *
 *  Disabled - which is the power-on state - it does nothing at all and the
 *  board behaves exactly as before.
 *
 * ===========================================================================
 *  WHY THE COUPLED FORM, AND NOT THE OBVIOUS ONE
 * ===========================================================================
 *  The textbook resonator is
 *
 *      y[n] = 2.r.cos(w).y[n-1] - r^2.y[n-2] + x[n]
 *
 *  and it is a poor choice here. The pole radius r is what sets Q, and it
 *  reaches the arithmetic only through the coefficient r^2. Rounding that
 *  coefficient moves the pole radially, which is precisely the direction that
 *  changes Q - so a resonator built this way has a Q you cannot set accurately
 *  once r gets close to 1, which is exactly where high Q lives.
 *
 *  The coupled form keeps two state variables in quadrature:
 *
 *      u' = c.u - s.v + x        c = r.cos(w)
 *      v' = s.u + c.v            s = r.sin(w)
 *
 *  The pole radius is sqrt(c^2 + s^2), so rounding the two coefficients trades
 *  one against the other and the radius stays well conditioned near the unit
 *  circle. Measured on a bit-exact model of this arithmetic, the Q that comes
 *  out is within 1% of the Q asked for, from Q = 30 to Q = 1000.
 *
 *  It also hands you u and v ninety degrees apart for nothing, which is the
 *  analytic signal - useful for feedback, and impossible from the direct form.
 *
 * ===========================================================================
 *  THE TIMING CONSTRAINT - READ BEFORE CHANGING ANY WIDTH
 * ===========================================================================
 *  A resonator is RECURSIVE: today's state depends on yesterday's. A plain
 *  register cannot be inserted into that loop, and retiming will not rescue it.
 *
 *  It was built as a one-clock multiply-add for that reason, and that did not
 *  close. From the 2026-08-07 routed report the two cascaded DSP48E1 stages
 *  cost 5.554 ns between them; with the flip-flop, the routing in and the setup
 *  at the far end the floor is 8.546 ns against 7.907 ns available. A rotation
 *  is two products summed, so two DSP stages is the minimum depth - the
 *  one-clock form could not have worked on this part however it was arranged.
 *
 *  It is now TWO-WAY LOOK-AHEAD: two banks holding the even and odd sample
 *  indices, each advancing by M^2 over two clocks in two registered stages. The
 *  loop is genuinely two clock edges long, so no multicycle constraint is
 *  needed - see "The resonator" below. Software must write COEF_C2 / COEF_S2 as
 *  well as COEF_C / COEF_S.
 *
 *  The widths still put ONE DSP slice on each multiply:
 *
 *      state       25 bits signed   - the DSP48E1's A port is 25 bits
 *      coefficient 18 bits signed   - its B port is 18 bits
 *
 *  Anything wider needs two slices cascaded on a single multiply. IF YOU WIDEN
 *  THESE, CHECK THE TIMING REPORT - do not assume. If timing fails, narrow
 *  rather than widen: 16-bit coefficients still reach Q = 300 with under 1%
 *  error.
 *
 *  For the record of what one recursive filter can cost: the stock
 *  oscilloscope's `dfilt1` equaliser produced 1173 failing endpoints until it
 *  was removed.
 *
 * ===========================================================================
 *  WHAT Q YOU CAN ASK FOR, AND WHY THERE IS A LIMIT
 * ===========================================================================
 *  A resonator AMPLIFIES by about Q at its own frequency. Drive it at full
 *  scale with Q = 1000 and it wants to swing a thousand times full scale. The
 *  state is 25 bits and the input is 14, so there are 11 bits - a factor of
 *  2048 - of headroom. Hence:
 *
 *      Q          largest drive        error in Q from rounding
 *      30         full scale           -1.8 %
 *      100        full scale           -0.6 %
 *      300        full scale           -0.4 %
 *      1000       full scale           -0.5 %
 *      3000       69 % of full scale   +0.5 %
 *      10000      21 % of full scale   +2.6 %
 *
 *  Beyond that the state saturates, which turns a resonance into a distorted
 *  mess that still looks vaguely resonant. The sticky clip flag in STATUS
 *  exists so that can never be mistaken for physics - CHECK IT after every
 *  sweep.
 *
 * ===========================================================================
 *  REGISTER MAP  -  base address 0x40400000  (system bus slot sys[4])
 * ===========================================================================
 *  One 32-bit access at a time, as everywhere else on this bus.
 *
 *  Offset  Name        R/W  Contents
 *  ------  ----------  ---  ----------------------------------------------------
 *   0x00   CTRL        RW   [0] enable  1 = this replaces the digitised input
 *                           [1] clear   write 1 to zero the state; self-clearing
 *   0x04   COEF_C      RW   [17:0] signed  c = r.cos(w0) x 2^17
 *   0x08   COEF_S      RW   [17:0] signed  s = r.sin(w0) x 2^17
 *                           w0 = 2.pi.f0/125e6,  r = 1 - pi.(f0/125e6)/Q
 *   0x0C   DELAY       RW   [7:0]  extra loop delay in clocks, 1..255.
 *                           The real loop has 119.87 ns of delay - about 15
 *                           clocks - from converters and cable. Inside the chip
 *                           there is almost none, so the emulation would be
 *                           optimistic without this. This is delay ON TOP OF the
 *                           module's own pipeline, which is 3 clocks since
 *                           2026-08-07, so write 12 to emulate the board's 15.
 *                           DO NOT SET 0. The delay line is a circular buffer,
 *                           and a read at distance 0 is a read of the address
 *                           being written this very cycle, which returns the
 *                           OLD contents - the sample from 256 clocks ago. So
 *                           0 does not mean "no delay"; it means 256 clocks,
 *                           silently (noted 2026-07-30; same failure shape as
 *                           the phase shifter's FIX 4, which clamps instead).
 *   0x10   OUT_SHIFT   RW   [4:0]  right shift from the 25-bit state to the
 *                           14-bit output, 0..15. About log2(Q) is right.
 *   0x14   STATUS      RO   [0] CLIPPED - the state saturated. Sticky, cleared
 *                               by CTRL[1]. If this is set the sweep is fiction
 *   0x18   PEEK_U      RO   [24:0] signed, the in-phase state
 *   0x1C   PEEK_V      RO   [24:0] signed, the quadrature state
 *   0x20   NOISE_TANK  RW   [4:0] amplitude as a RIGHT SHIFT (6 dB per step),
 *                           [8] enable. Johnson noise of the coil: injected
 *                           INTO the resonator's input, so it comes out
 *                           filtered by the resonance - a Lorentzian bump,
 *                           exactly as the real tank's thermal noise does
 *   0x24   NOISE_OUT   RW   same layout. Amplifier noise: added AFTER the
 *                           resonator, so it is a flat floor underneath.
 *                           Both added 2026-07-30; both read back
 *   0x28   COEF_C2     RW   [17:0] signed  c2 = r^2.cos(2.w0) x 2^17
 *   0x2C   COEF_S2     RW   [17:0] signed  s2 = r^2.sin(2.w0) x 2^17
 *                           Added 2026-08-07. The recursion now advances TWO
 *                           samples per update, so it turns by 2.w0 and shrinks
 *                           by r^2 - see "two-way look-ahead" below. COEF_C and
 *                           COEF_S are still required: they carry the drive
 *                           term M.b[n]. Write all four.
 *
 *  Any other offset reads as zero.
 *
 * ===========================================================================
 *  THE NOISE SOURCES  -  added 2026-07-30 for Test Stage 9
 * ===========================================================================
 *  A real detection spectrum is not a clean curve: it is the coil's own
 *  thermal (Johnson) noise shaped by the resonance, sitting on the flat
 *  noise of the first amplifier. Emulating a real measurement therefore
 *  needs both, with amplitudes software can set - that is what makes the
 *  signal-to-noise ratio configurable.
 *
 *  HOW THE RANDOMNESS IS MADE. Two free-running 64-bit xorshift generators
 *  (a shift-and-XOR scramble that walks a 2^64-1 sequence; three levels of
 *  XOR, timing-trivial). Real thermal noise is Gaussian; a raw generator is
 *  uniform. Summing four independent 14-bit lanes of the state gives the
 *  bell shape (the same central-limit reasoning as dice: one die is flat,
 *  four dice are a bell). Good enough for spectra by a wide margin; it is
 *  not cryptography and does not need to be. The generators free-run from
 *  fixed seeds, so the noise is fresh every run - deliberately: averaging
 *  tests must never be able to average against a repeat of the same noise.
 *
 *  Per-sample RMS before the shift is about 9460 counts (four uniforms of
 *  width 16384 summed); each shift step halves it. Software calibrates the
 *  exact value in Stage 9 rather than trusting this arithmetic.
 *
 *  TIMING - why this addition is safe in a module that forbids additions.
 *  The recursive one-clock multiply-add is UNTOUCHED. The tank noise joins
 *  the DRIVE, not the recursion: drive + noise are summed into a register
 *  one clock ahead, and the recursion adds that register exactly as it
 *  added the raw drive before. (Side effect: the drive leg gains one clock
 *  of latency, [approximately] 8 ns more emulated loop delay. Stage 8 fits the loop
 *  phase empirically, so nothing there needed changing; anyone comparing
 *  against a pre-noise build should know.) The output noise joins in the
 *  non-recursive output stage, which pipelines freely.
 */

`timescale 1ns / 1ps

module red_pitaya_resonator #(
  parameter integer DWI   = 14,   // input and output width, signed
  parameter integer SW    = 25,   // state width - one DSP A port
  parameter integer CW    = 18,   // coefficient width - one DSP B port
  parameter integer DLYW  = 8     // log2 of the extra delay line
)(
  // ---- clock and reset ----
  input                      clk_i    ,  //!< 125 MHz processing clock
  input                      rstn_i   ,  //!< active-LOW synchronous reset

  // ---- data ----
  input      signed [DWI-1:0] dat_i   ,  //!< what the board is sending out
  output reg signed [DWI-1:0] dat_o   ,  //!< what it would hear back
  output                      ena_o   ,  //!< 1 = use dat_o instead of the ADC

  // ---- system bus ----
  input      [ 32-1: 0] sys_addr  ,
  input      [ 32-1: 0] sys_wdata ,
  input                 sys_wen   ,
  input                 sys_ren   ,
  output reg [ 32-1: 0] sys_rdata ,
  output reg            sys_err   ,
  output reg            sys_ack
);

localparam integer SHIFT = CW - 1;              // coefficients are Q1.(CW-1)
localparam signed [SW-1:0] SAT_HI =  {1'b0, {(SW-1){1'b1}}};
localparam signed [SW-1:0] SAT_LO =  {1'b1, {(SW-1){1'b0}}};

//---------------------------------------------------------------------------------
//  Software-written configuration
//---------------------------------------------------------------------------------
reg                       set_ena;
reg                       set_clr;
reg  signed [ CW-1: 0]    set_c;         // 0x04  r.cos(w0)   x 2^17
reg  signed [ CW-1: 0]    set_s;         // 0x08  r.sin(w0)   x 2^17
reg  signed [ CW-1: 0]    set_c2;        // 0x28  r^2.cos(2w0) x 2^17
reg  signed [ CW-1: 0]    set_s2;        // 0x2C  r^2.sin(2w0) x 2^17
reg         [ DLYW-1: 0]  set_dly;
reg         [ 5-1: 0]     set_oshift;
reg         [ 5-1: 0]     set_ntank_sh;   // 0x20[4:0] tank-noise right shift
reg                       set_ntank_en;   // 0x20[8]   tank-noise enable
reg         [ 5-1: 0]     set_nout_sh;    // 0x24[4:0] output-noise right shift
reg                       set_nout_en;    // 0x24[8]   output-noise enable

assign ena_o = set_ena;

//---------------------------------------------------------------------------------
//  Noise generation (see the header section THE NOISE SOURCES for the why)
//
//  Two independent xorshift64 generators, free-running from fixed non-zero
//  seeds. Each clock: three shift-and-XOR scrambles. Four signed 14-bit lanes
//  of each state are summed into an approximately Gaussian sample (central
//  limit theorem - four dice make a bell), scaled by an arithmetic right
//  shift (6 dB per step), and REGISTERED before use, so no noise arithmetic
//  ever appears in the same clock as the resonator's recursive multiply-add.
//---------------------------------------------------------------------------------
reg  [63:0] lfsr_a, lfsr_b;

wire [63:0] xa1 = lfsr_a ^ (lfsr_a << 13);
wire [63:0] xa2 = xa1    ^ (xa1    >>  7);
wire [63:0] xa3 = xa2    ^ (xa2    << 17);
wire [63:0] xb1 = lfsr_b ^ (lfsr_b << 13);
wire [63:0] xb2 = xb1    ^ (xb1    >>  7);
wire [63:0] xb3 = xb2    ^ (xb2    << 17);

// four signed 14-bit lanes summed: range +-32768, comfortably a 17-bit signed
wire signed [16:0] gauss_a = $signed(lfsr_a[13: 0]) + $signed(lfsr_a[27:14])
                           + $signed(lfsr_a[41:28]) + $signed(lfsr_a[55:42]);
wire signed [16:0] gauss_b = $signed(lfsr_b[13: 0]) + $signed(lfsr_b[27:14])
                           + $signed(lfsr_b[41:28]) + $signed(lfsr_b[55:42]);

reg  signed [16:0] noise_tank_r;   // registered, scaled, gated tank noise
reg  signed [16:0] noise_out_r;    // registered, scaled, gated output noise

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    lfsr_a       <= 64'h9E3779B97F4A7C15;   // fixed non-zero seeds; the value
    lfsr_b       <= 64'hD1B54A32D192ED03;   // only matters in that it is not 0
    noise_tank_r <= 17'sd0;
    noise_out_r  <= 17'sd0;
  end else begin
    lfsr_a       <= xa3;
    lfsr_b       <= xb3;
    noise_tank_r <= set_ntank_en ? (gauss_a >>> set_ntank_sh) : 17'sd0;
    noise_out_r  <= set_nout_en  ? (gauss_b >>> set_nout_sh ) : 17'sd0;
  end
end

//---------------------------------------------------------------------------------
//  The resonator: two-way look-ahead, two banks, two clocks per update
//
//  WHY IT IS NOT ONE CLOCK ANY MORE. From the 2026-08-07 routed report the two
//  cascaded DSP48E1 stages cost 5.554 ns between them; with the flip-flop, the
//  routing in and the setup at the far end the floor is 8.546 ns against 7.907
//  available. A rotation is two products summed, so two DSP stages is the
//  minimum depth - no rearrangement of the fabric was going to close 8 ns.
//
//  A register cannot go inside a recursive loop, but two samples can be
//  computed per update with the extra clock absorbed into the coefficients:
//
//      x[n+1] = M   x[n]   + b[n]                 M   = (1/2^S)[[c,-s],[s,c]]
//      x[n+2] = M^2 x[n]   + M b[n] + b[n+1]      M^2 = r^2 Rot(2 w0)
//
//  M is a scaled rotation, so M^2 is just the rotation doubled and the radius
//  squared - the squared coefficients are computed in software exactly the way
//  c and s are, and written to COEF_C2 / COEF_S2.
//
//  TWO BANKS hold the even and odd sample indices. Each advances by M^2 and
//  takes two clocks to do it, in two registered stages:
//
//      stage 1   acc <= c2*u - s2*v                (two cascaded DSPs)
//      stage 2   u   <= sat((acc + add) >>> SHIFT) (one adder, shift, clamp)
//
//  The banks are a clock apart, so one is always in stage 1 while the other is
//  in stage 2: both stages are busy every clock and the output still changes
//  every clock. The path genuinely crosses two clock edges, so this needs NO
//  multicycle constraint - a clock enable would not have been enough, because
//  static timing analysis is edge-based and would still have checked it in one.
//
//  THE DRIVE stays outside the loop. c*d and s*d are registered, and the
//  pre-shift constant is folded in by concatenation as before, so stage 2 sees
//  one ready-made addend. Consecutive clocks carry consecutive (b[n], b[n+1])
//  pairs, and each bank takes the pair it needs; b[n] is used by both banks,
//  which is what the algebra above asks for.
//
//  LATENCY. The drive leg gains one clock, the output register one more, and the
//  output-stage register added below one more again - three clocks (24 ns) of
//  module pipeline in total. Set DELAY three lower than the loop delay wanted:
//  DELAY = 12 for the board's real 15. Stage 8 fits the loop phase empirically
//  and does not care; the Step 1 self-test does.
//
//  KNOWN ARTEFACT - a mirror line at fs/2 - f0. Two interleaved banks are the
//  two polyphase components of one sequence, and quantisation stops their
//  relative phase being exactly w0. The residue lands at fs/2 - f0: 22.5 MHz
//  for a 40 MHz pole, 46 to 57 dB down (measured by
//  software/validation/validate_resonator_pipelined.py). It cannot enter a
//  measurement - the receiver's clean window is +-12 kHz and the image sits
//  megahertz away - but it WILL show in a wide band survey if the emulator is
//  left enabled during one.
//
//  Rounding is unchanged: half an LSB before the shift, because truncation
//  always biases towards minus infinity and a loop with gain near one
//  accumulates that into a drift that looks like a real resonance.
//---------------------------------------------------------------------------------
localparam integer PW = SW + CW;                 // 43: one product
localparam signed [PW:0] ROUND = {{(PW+1-SHIFT){1'b0}}, 1'b1, {(SHIFT-1){1'b0}}};

reg                   ph;                        // 0/1: which bank is in stage 1
reg signed [ SW-1: 0] uA, vA, uB, vB;            // the two state banks
reg signed [ SW-1: 0] u,  v;                     // the bank that updated last
reg                   clipped;

//---------------------------------------------------------------------------------
//  The drive: input plus tank noise, PRE-SUMMED INTO A REGISTER (2026-07-30).
//
//  The recursion below must stay a single clock, so nothing may be added to
//  it. Summing drive and noise one clock ahead keeps the recursive path
//  identical to the noiseless original - the recursion still adds exactly one
//  registered term. The drive leg gains one clock of latency ([approximately] 8 ns more
//  emulated loop delay); see the header's timing note.
//---------------------------------------------------------------------------------
reg signed [17:0] drive_r;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0)
    drive_r <= 18'sd0;
  else
    // $signed() on both concatenations: a concatenation is always unsigned,
    // and these must add as two's-complement values (see the note at out_pre)
    drive_r <= $signed({{(18-DWI){dat_i[DWI-1]}}, dat_i})
             + $signed({noise_tank_r[16], noise_tank_r});
end

//---------------------------------------------------------------------------------
//  The drive, pipelined outside the loop.
//
//  drive_r is the input plus tank noise, already registered above. cd_r and
//  sd_r are its products with c and s - the M b[n] term. add_u also carries
//  b[n+1] and the rounding constant, and because ROUND is a single 1 at bit
//  SHIFT-1 while drive<<SHIFT has nothing below bit SHIFT, that part is a
//  CONCATENATION rather than an adder.
//---------------------------------------------------------------------------------
reg signed [ CW+18-1: 0] cd_r, sd_r;
reg signed [ PW: 0]      add_u, add_v;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    cd_r  <= {(CW+18){1'b0}};
    sd_r  <= {(CW+18){1'b0}};
    add_u <= {(PW+1){1'b0}};
    add_v <= {(PW+1){1'b0}};
  end else begin
    cd_r  <= set_c * drive_r;
    sd_r  <= set_s * drive_r;
    // cd_r is c*d[n-1]; drive_r is d[n]. Together they are M b[n] + b[n+1].
    add_u <= cd_r + $signed({{(PW+1-18-SHIFT){drive_r[17]}}, drive_r,
                             1'b1, {(SHIFT-1){1'b0}}});
    add_v <= sd_r + ROUND;
  end
end

//---------------------------------------------------------------------------------
//  Stage 1 - the rotation, one bank per clock. Two DSPs each; Vivado cascades
//  them through PCOUT/PCIN and registers the result in the second DSP's own P
//  register, which is what makes this side of the split fast.
//---------------------------------------------------------------------------------
reg signed [ PW: 0] accA_u, accA_v, accB_u, accB_v;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0 || set_clr || !set_ena) begin
    accA_u <= {(PW+1){1'b0}};  accA_v <= {(PW+1){1'b0}};
    accB_u <= {(PW+1){1'b0}};  accB_v <= {(PW+1){1'b0}};
  end else if (ph == 1'b0) begin
    accA_u <= set_c2 * uA - set_s2 * vA;
    accA_v <= set_s2 * uA + set_c2 * vA;
  end else begin
    accB_u <= set_c2 * uB - set_s2 * vB;
    accB_v <= set_s2 * uB + set_c2 * vB;
  end
end

//---------------------------------------------------------------------------------
//  Stage 2 - add the drive, shift, clamp. Saturation is the top-two-bits test:
//  u_nxt is SW+1 bits and SAT_HI/SAT_LO are the extremes of SW, so "does it
//  fit" is "are the top two bits the same" - one XOR, not a comparison.
//---------------------------------------------------------------------------------
wire signed [ PW+1: 0] sumA_u = accA_u + add_u;
wire signed [ PW+1: 0] sumA_v = accA_v + add_v;
wire signed [ PW+1: 0] sumB_u = accB_u + add_u;
wire signed [ PW+1: 0] sumB_v = accB_v + add_v;

wire signed [ SW: 0] uA_nxt = sumA_u >>> SHIFT;
wire signed [ SW: 0] vA_nxt = sumA_v >>> SHIFT;
wire signed [ SW: 0] uB_nxt = sumB_u >>> SHIFT;
wire signed [ SW: 0] vB_nxt = sumB_v >>> SHIFT;

wire uA_over = uA_nxt[SW] ^ uA_nxt[SW-1];
wire vA_over = vA_nxt[SW] ^ vA_nxt[SW-1];
wire uB_over = uB_nxt[SW] ^ uB_nxt[SW-1];
wire vB_over = vB_nxt[SW] ^ vB_nxt[SW-1];

//  The clamp, written out per bank rather than as a function - the rest of this
//  module uses no functions and this is the same conditional the single-clock
//  version used.
wire signed [SW-1:0] uA_cl = uA_over ? (uA_nxt[SW] ? SAT_LO : SAT_HI) : uA_nxt[SW-1:0];
wire signed [SW-1:0] vA_cl = vA_over ? (vA_nxt[SW] ? SAT_LO : SAT_HI) : vA_nxt[SW-1:0];
wire signed [SW-1:0] uB_cl = uB_over ? (uB_nxt[SW] ? SAT_LO : SAT_HI) : uB_nxt[SW-1:0];
wire signed [SW-1:0] vB_cl = vB_over ? (vB_nxt[SW] ? SAT_LO : SAT_HI) : vB_nxt[SW-1:0];

//  Bank A is in stage 2 when ph is 1 - the clock after it was in stage 1 - and
//  bank B on the opposite phase. u and v then take whichever bank wrote last,
//  which is a register-to-register hop through one multiplexer.
always @(posedge clk_i) begin
  if (rstn_i == 1'b0 || set_clr) begin
    ph      <= 1'b0;
    uA      <= {SW{1'b0}};  vA <= {SW{1'b0}};
    uB      <= {SW{1'b0}};  vB <= {SW{1'b0}};
    u       <= {SW{1'b0}};  v  <= {SW{1'b0}};
    clipped <= 1'b0;
  end else if (set_ena) begin
    ph <= ~ph;
    u  <= ph ? uA : uB;
    v  <= ph ? vA : vB;
    if (ph == 1'b1) begin
      uA <= uA_cl;
      vA <= vA_cl;
      if (uA_over || vA_over) clipped <= 1'b1;
    end else begin
      uB <= uB_cl;
      vB <= vB_cl;
      if (uB_over || vB_over) clipped <= 1'b1;
    end
  end else begin
    ph <= 1'b0;
    uA <= {SW{1'b0}};  vA <= {SW{1'b0}};
    uB <= {SW{1'b0}};  vB <= {SW{1'b0}};
    u  <= {SW{1'b0}};  v  <= {SW{1'b0}};
  end
end

//---------------------------------------------------------------------------------
//  Scale the state down to the output width, and add the amplifier noise.
//
//  This stage is NOT recursive - nothing here feeds back into u or v - so an
//  extra addition costs slack on an ordinary one-clock path, not on the loop.
//  The noise term is already registered and gated (zero when disabled), so
//  with NOISE_OUT off this reduces to exactly the original expression.
//---------------------------------------------------------------------------------
//  $signed() on the concatenation is LOAD-BEARING. A concatenation is always
//  unsigned, and one unsigned operand makes the whole addition unsigned - so
//  without it, a negative u_scaled would be ZERO-extended and the saturation
//  logic would fire wrongly for the entire negative half of every cycle.
//  This is the same trap as the corrector's one real hardware bug (see
//  CHANGELOG: "a concatenation in Verilog is unsigned").
wire signed [ SW-1: 0] u_scaled = u >>> set_oshift;
wire signed [ SW: 0]   out_pre  = u_scaled + $signed({{(SW+1-17){noise_out_r[16]}}, noise_out_r});

wire signed [DWI-1:0] out_sat =
       (out_pre >  $signed({{(SW-DWI+2){1'b0}}, {(DWI-1){1'b1}}})) ?  {1'b0, {(DWI-1){1'b1}}} :
       (out_pre <  $signed({{(SW-DWI+2){1'b1}}, {(DWI-1){1'b0}}})) ?  {1'b1, {(DWI-1){1'b0}}} :
                                                                      out_pre[DWI-1:0];

//---------------------------------------------------------------------------------
//  FIX (2026-08-07) - the saturated output is REGISTERED before the delay line.
//
//  THE PROBLEM. After the two-way look-ahead closed the recursion, the last six
//  failing endpoints in the whole design were all of the same shape:
//
//      set_oshift -> 25-bit variable (barrel) shift -> noise add -> two
//      saturation compares -> delay-line memory write
//
//  measuring 8.251 ns against 8 ns, i.e. WNS -0.251 ns. A variable shift is a
//  five-level multiplexer tree, and it sat in front of an add and a compare with
//  a memory setup at the end. Every operation is real work, so there was nothing
//  to hoist - the stage simply needed splitting.
//
//  THE FIX. One register between the saturation and the memory write. This stage
//  is NOT recursive - nothing downstream of `u` returns to `u` - so a register
//  here is free of the constraint that forbade one inside the loop, and it costs
//  only latency.
//
//  THE COST: ONE MORE CLOCK (8 ns). Fold it into DELAY: the module's own
//  pipeline is now three clocks, so DELAY = 12 gives the board's real 15. The
//  notebook's Emulator.config() default moved 13 -> 12 to match. Stage 8 fits
//  the loop phase empirically and does not depend on this number, but the Step 1
//  self-test does.
//---------------------------------------------------------------------------------
reg signed [DWI-1:0] out_sat_r;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) out_sat_r <= {DWI{1'b0}};
  else                out_sat_r <= out_sat;
end

//---------------------------------------------------------------------------------
//  Extra loop delay
//
//  The real loop carries 119.87 ns - about 15 clocks - of converter and cable
//  delay, and that delay is a phase that grows with frequency: 43 degrees at
//  1 MHz, 286 degrees at 40 MHz. Inside the chip there is almost none, so
//  without this the emulation would flatter the feedback system by removing the
//  very thing the phase shifter exists to compensate.
//---------------------------------------------------------------------------------
reg signed [DWI-1:0] dly_buf [0:(1<<DLYW)-1];
reg        [DLYW-1:0] dly_wp;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    dly_wp <= {DLYW{1'b0}};
    dat_o  <= {DWI{1'b0}};
  end else begin
    dly_buf[dly_wp] <= out_sat_r;
    dly_wp          <= dly_wp + 1'b1;
    dat_o           <= dly_buf[dly_wp - set_dly];
  end
end

//---------------------------------------------------------------------------------
//  System bus
//---------------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    set_ena    <= 1'b0;          // does nothing until asked - the board is
    set_clr    <= 1'b0;          // unchanged at power-on
    set_c      <= {CW{1'b0}};
    set_s      <= {CW{1'b0}};
    set_c2     <= {CW{1'b0}};
    set_s2     <= {CW{1'b0}};
    set_dly    <= {DLYW{1'b0}};
    set_oshift <= 5'd0;
    set_ntank_sh <= 5'd0;        // noise off at power-on, like everything else
    set_ntank_en <= 1'b0;
    set_nout_sh  <= 5'd0;
    set_nout_en  <= 1'b0;
  end else begin
    set_clr <= 1'b0;             // one-shot
    if (sys_wen) begin
      case (sys_addr[19:0])
        20'h00 : begin set_ena <= sys_wdata[0]; set_clr <= sys_wdata[1]; end
        20'h04 :       set_c      <= sys_wdata[CW-1:0];
        20'h08 :       set_s      <= sys_wdata[CW-1:0];
        20'h28 :       set_c2     <= sys_wdata[CW-1:0];
        20'h2C :       set_s2     <= sys_wdata[CW-1:0];
        20'h0C :       set_dly    <= sys_wdata[DLYW-1:0];
        20'h10 :       set_oshift <= sys_wdata[4:0];
        20'h20 : begin set_ntank_sh <= sys_wdata[4:0]; set_ntank_en <= sys_wdata[8]; end
        20'h24 : begin set_nout_sh  <= sys_wdata[4:0]; set_nout_en  <= sys_wdata[8]; end
        default: ;
      endcase
    end
  end
end

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    sys_err   <= 1'b0;
    sys_ack   <= 1'b0;
    sys_rdata <= 32'h0;
  end else begin
    sys_err <= 1'b0;
    sys_ack <= sys_wen | sys_ren;
    case (sys_addr[19:0])
      20'h00 : sys_rdata <= {30'h0, 1'b0, set_ena};
      20'h04 : sys_rdata <= {{(32-CW){set_c[CW-1]}}, set_c};
      20'h08 : sys_rdata <= {{(32-CW){set_s[CW-1]}}, set_s};
      20'h0C : sys_rdata <= {{(32-DLYW){1'b0}}, set_dly};
      20'h10 : sys_rdata <= {27'h0, set_oshift};
      20'h14 : sys_rdata <= {31'h0, clipped};
      20'h18 : sys_rdata <= {{(32-SW){u[SW-1]}}, u};
      20'h1C : sys_rdata <= {{(32-SW){v[SW-1]}}, v};
      20'h20 : sys_rdata <= {23'h0, set_ntank_en, 3'h0, set_ntank_sh};
      20'h24 : sys_rdata <= {23'h0, set_nout_en,  3'h0, set_nout_sh};
      20'h28 : sys_rdata <= {{(32-CW){set_c2[CW-1]}}, set_c2};
      20'h2C : sys_rdata <= {{(32-CW){set_s2[CW-1]}}, set_s2};
      default: sys_rdata <= 32'h0;
    endcase
  end
end

endmodule
