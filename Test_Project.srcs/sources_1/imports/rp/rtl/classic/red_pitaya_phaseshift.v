/**
 * @brief Red Pitaya variable phase-shift + gain module (IQ architecture).
 *
 * @Author Alex (Imperial CCM internship) - custom module
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * Implements the variable phase shifter of Herkenhoff et al.,
 * "A digital feedback system for advanced ion manipulation techniques in
 * Penning traps", Rev. Sci. Instrum. 92, 103201 (2021).
 *
 * ===========================================================================
 *  CHANGE LOG / FIXES (why this file looks the way it does)
 * ===========================================================================
 *  FIX 1 [Synth 8-2715] "syntax error near buf":
 *        The delay memory was originally called `buf`, a RESERVED Verilog
 *        keyword (buffer-gate primitive). Renamed to a normal name.
 *
 *  FIX 2 (.sv -> .v):
 *        The module is plain Verilog-2001 (like red_pitaya_pid.v), so the file
 *        was renamed from .sv to .v. The .sv extension did not cause any error.
 *
 *  FIX 3 [Place 30-4 / 30-99] "Design utilization is very high" (placer failed
 *        on the XC7Z010, only 17,600 LUTs):
 *        The delay line was FIRST built as a 1024-deep shift register made of
 *        flip-flops, with the two quadrature taps read at a VARIABLE index.
 *        That cost ~14,000 flip-flops PLUS enormous F7/F8 multiplexer trees
 *        (the variable-index read of a 1024-entry array), which overflowed the
 *        small device. FIX: the delay line is now a CIRCULAR BUFFER in BLOCK
 *        RAM - a write pointer plus two registered reads. Block RAM is almost
 *        free on this device (60 tiles), so the ~14k flip-flops and the giant
 *        muxes disappear and the design fits.
 *
 *        SIDE EFFECT of block RAM: a registered read adds one clock of latency.
 *        The whole datapath now has a FIXED latency of L = 2 samples (measured,
 *        constant vs frequency). Because it is a pure transport delay it just
 *        adds a constant phase lag of 360*L*f_sig/f_clk degrees. The HOST
 *        (Jupyter) cancels it by requesting  phi_eff = phi - 360*L*f_sig/f_clk;
 *        the IQ rotation then lands exactly on the requested phase. This module
 *        needs no change for that - it is a host-side correction. (See notebook.)
 * ===========================================================================
 *
 *  WHAT THE MODULE COMPUTES
 *  The output is   y[n] = A*cos(phi)*I[n] + A*sin(phi)*Q[n]
 *    I : in-phase   component = the input signal itself (delay 0)
 *    Q : quadrature component = the input delayed by ~90 degrees, i.e. by a
 *        quarter period. In clock cycles that delay is D = f_clk/(4*f_sig).
 *  D is usually fractional, so Q is a linear blend of the delay line at
 *  floor(D) and ceil(D)=floor(D)+1 with weights (1-d) and d, d = D-floor(D).
 *
 *  Trig and gain are done on the HOST, which writes two ready-made signed
 *  fixed-point coefficients:  set_ci = A*cos(phi),  set_cq = A*sin(phi).
 *
 *  Ports are drop-in compatible with red_pitaya_pid, so this module reuses the
 *  PID's system-bus slot sys[3] (base address 0x40300000) and the existing DAC
 *  summation path in red_pitaya_top. Single channel: CH A processed, CH B = 0.
 */

module red_pitaya_phaseshift #(
  parameter integer DWI   = 14,      // data word width (ADC/DAC are 14-bit signed)
  parameter integer DWC   = 16,      // coefficient width (signed Q2.14)
  parameter integer FRAC  = 14,      // fractional bits: 1.0 == 2^14 == 16384
  parameter integer DEPTH = 1024,    // delay-line length (MUST be a power of 2)
  parameter integer DLYW  = 10       // delay index width; 2^DLYW == DEPTH
)(
   // ---- data path ----
   input                     clk_i     ,  //!< 125 MHz processing clock
   input                     rstn_i    ,  //!< active-LOW synchronous reset
   input      [ DWI-1: 0]    dat_a_i   ,  //!< input  CH A (ADC / signal generator)
   input      [ DWI-1: 0]    dat_b_i   ,  //!< input  CH B (unused)
   output     [ DWI-1: 0]    dat_a_o   ,  //!< output CH A (phase/gain shifted)
   output     [ DWI-1: 0]    dat_b_o   ,  //!< output CH B (zero)

   // ---- coefficients from the sequencer (Stage 11) ----
   //  When ext_sel_i is high the two coefficients come from these inputs
   //  instead of from the software registers, so a state machine can rewrite
   //  the feedback phase at exact times. Tie ext_sel_i low and this module
   //  behaves exactly as it did before.
   input      [ DWC-1: 0]    ci_ext_i  ,  //!< A*cos(phi) from the sequencer
   input      [ DWC-1: 0]    cq_ext_i  ,  //!< A*sin(phi) from the sequencer
   input                     ext_sel_i ,  //!< 1 = use the sequencer's pair

   // ---- system bus ----
   input      [ 32-1: 0]     sys_addr  ,  //!< bus address
   input      [ 32-1: 0]     sys_wdata ,  //!< bus write data
   input                     sys_wen   ,  //!< write enable
   input                     sys_ren   ,  //!< read  enable
   output reg [ 32-1: 0]     sys_rdata ,  //!< read data to CPU
   output reg                sys_err   ,  //!< error flag (always 0)
   output reg                sys_ack      //!< acknowledge
);

//---------------------------------------------------------------------------------
//  Host-written configuration registers
//---------------------------------------------------------------------------------
reg signed [ DWC-1: 0] set_ci    ;  // A*cos(phi) Q2.14 signed            (0x00)
reg signed [ DWC-1: 0] set_cq    ;  // A*sin(phi) Q2.14 signed            (0x04)
reg        [ DLYW-1:0] set_dly   ;  // floor(D) whole-cycle delay         (0x08)
reg        [ FRAC-1:0] set_delta ;  // d = D-floor(D) unsigned Q0.14      (0x0C)
reg                    set_byp   ;  // 1 = bypass (pass input through)    (0x10)

//---------------------------------------------------------------------------------
//  Delay line = CIRCULAR BUFFER in BLOCK RAM  (FIX 3)
//  Instead of shifting 1024 flip-flops every clock, we keep the data still and
//  move a write pointer. Sample x[n] goes to dly_mem[wp]; the sample delayed by
//  m clocks is at dly_mem[wp-m]. Because DEPTH is a power of two, the DLYW-bit
//  pointer arithmetic wraps around automatically (no explicit modulo needed).
//---------------------------------------------------------------------------------
reg  [ DWI-1:0] dly_mem [0:DEPTH-1];   // inferred as block RAM (2 read ports)
reg  [ DLYW-1:0] wp;                    // write pointer, wraps mod DEPTH

//---------------------------------------------------------------------------------
//  FIX 4 - guard against set_dly = 0  (matters at high signal frequencies)
//
//  D = f_clk/(4*f_sig) falls below 1 once f_sig exceeds f_clk/4 = 31.25 MHz, so
//  floor(D) = 0 and the host would naturally write set_dly = 0. That setting is
//  BROKEN: addr_f would equal wp, the address being written this very cycle, and
//  a block RAM read at the address being written returns the OLD contents - the
//  sample from DEPTH (1024) clocks ago, not a zero-clock delay. The quadrature
//  component would be meaningless while looking perfectly plausible on a scope.
//
//  Clamping to a minimum of 1 makes the failure impossible. It does NOT make
//  set_dly = 0 correct - it substitutes a 1-sample delay - so the status bit at
//  offset 0x14 reports when the clamp is active, and the host should react by
//  choosing a valid delay instead of relying on the clamp.
//
//  THE RIGHT FIX IS ON THE HOST SIDE. A 90 degree shift is equivalent to 90
//  degrees plus any whole number of signal periods, so use
//
//      D = f_clk/(4*f_sig)  +  k * f_clk/f_sig       for integer k >= 1
//
//  and pick the k that lands the fractional part closest to 0 or 1, where the
//  two-tap interpolator is most accurate. At f_sig = 40 MHz, k = 2 gives
//  D = 7.031 (set_dly = 7, delta = 0.031), which is the best available setting:
//  -0.39 dB gain error and -1.90 degrees phase error, both constant at a fixed
//  frequency and therefore calibratable. The naive k = 0 choice would give
//  -2.90 dB and +9.15 degrees, on top of tripping the bug above.
//---------------------------------------------------------------------------------
wire dly_clamped = (set_dly == {DLYW{1'b0}});

//---------------------------------------------------------------------------------
//  FIX 7 [Timing 38-282] - the clamped delay is now REGISTERED.
//
//  THE PROBLEM
//  FIX 4 (above) computed the clamp combinationally, which put a 10-bit
//  comparison and a multiplexer directly in front of the delay-line read
//  address. The resulting chain was
//
//      set_dly register -> LUT5 -> LUT6 -> 10-bit subtract -> memory address
//                       -> distributed-RAM read -> multiplier input
//
//  and it measured 8.098 ns against an 8 ns clock, missing by 0.260 ns. It was
//  4 of the 7 remaining failing endpoints after the acquisition system was
//  added. In other words, FIX 4 solved a correctness bug and created a timing
//  one - worth recording, because that is easy to do and easy to miss.
//
//  Note how the delay divides: only 1.958 ns of it is logic. The other 6.140 ns
//  is wiring, and most of that is one net - the read address, which fans out to
//  229 loads. That fan-out is a consequence of how the delay line is built:
//  it needs one write port and TWO independent read addresses, which is three
//  ports, and block RAM only offers two. So Vivado builds it from LUT-based
//  distributed RAM instead, and every one of those small memories needs the
//  address delivered to it.
//
//  THE FIX
//  set_dly is a configuration value that software writes perhaps once a minute.
//  There is no reason to re-evaluate the clamp 125 million times a second, so it
//  is computed once into a register. That takes both lookup tables and their
//  routing out of the path, leaving only the subtract and the memory read.
//
//  Behaviour is unchanged. A newly written set_dly takes one extra clock (8 ns)
//  to take effect, which is irrelevant for a value set by hand, and the signal
//  path latency stays at L = 3 samples - so L_PIPE = 3 in the host remains right.
//
//  (Same reasoning as FIX 5, which did this for the interpolation weights. If a
//  future edit adds anything else derived from a configuration register, register
//  it rather than computing it in the datapath.)
//---------------------------------------------------------------------------------
reg [ DLYW-1:0] dly_eff;

always @(posedge clk_i) begin
   if (rstn_i == 1'b0) dly_eff <= {{(DLYW-1){1'b0}}, 1'b1};   // minimum valid delay
   else                dly_eff <= dly_clamped ? {{(DLYW-1){1'b0}}, 1'b1} : set_dly;
end

// Read addresses for the two quadrature taps (combinational, from current wp).
wire [ DLYW-1:0] addr_f = wp - dly_eff;          // floor(D) samples old
wire [ DLYW-1:0] addr_c = wp - dly_eff - 1'b1;   // floor(D)+1 samples old

// write pointer (has reset)
always @(posedge clk_i)
   if (rstn_i == 1'b0) wp <= {DLYW{1'b0}};
   else                wp <= wp + 1'b1;

// memory WRITE - no reset, so it maps cleanly to block RAM
always @(posedge clk_i)
   dly_mem[wp] <= dat_a_i;

// memory READS (registered = 1 clock latency => block RAM output register),
// plus one register on the I path so I and the read line up in time.
reg signed [ DWI-1:0] q_flr;   // dly_mem[addr_f], registered
reg signed [ DWI-1:0] q_cel;   // dly_mem[addr_c], registered
reg signed [ DWI-1:0] i_d1;    // input delayed 1 clock to match read latency
always @(posedge clk_i) begin
   q_flr <= dly_mem[addr_f];
   q_cel <= dly_mem[addr_c];
   i_d1  <= dat_a_i;
end

//---------------------------------------------------------------------------------
//  Quadrature blend: q = ( (1-d)*q_flr + d*q_cel ) >> FRAC
//
//  FIX 5 [Timing 38-282] - interpolation weights are now PRE-COMPUTED.
//
//  THE PROBLEM
//  The weights used to be derived combinationally from set_delta:
//
//      wire [FRAC:0] w0 = (1 << FRAC) - set_delta;   // 15-bit subtract
//      wire [FRAC:0] w1 = {1'b0, set_delta};
//
//  which put a 15-bit subtraction directly in front of the multiplier. The
//  resulting chain - register, 4 carry stages, DSP48 multiply, add, register -
//  measured 7.698 ns against an 8 ns clock, and after clock skew and
//  uncertainty came out 1.437 ns short. It accounted for ALL 101 remaining
//  setup violations in the design (the other 1173 were the scope's equaliser).
//
//  THE FIX
//  set_delta is a configuration value. It changes when the host writes it -
//  perhaps once a minute - not once per sample. There is no reason to redo the
//  subtraction 125 million times a second. Computing it once into a register
//  removes it from the signal path completely, leaving only multiply-and-add
//  between registers.
//
//  WHAT THIS DOES NOT CHANGE
//  The signal path latency is unchanged at L = 2 samples, so the host's
//  existing latency compensation still applies exactly as before. The only
//  effect is that a newly written set_delta takes one extra clock cycle (8 ns)
//  to take effect, which is irrelevant for a value the software sets by hand.
//  Both weights are registered on the same clock edge, so they can never be
//  momentarily inconsistent with each other.
//---------------------------------------------------------------------------------
reg [ FRAC:0]  w0_reg;   // (1 - d), up to 16384 -> needs FRAC+1 = 15 bits
reg [ FRAC:0]  w1_reg;   // d

always @(posedge clk_i) begin
   if (rstn_i == 1'b0) begin
      // Reset to d = 0, i.e. weights (1, 0): the quadrature tap is taken
      // entirely from the floor(D) sample, with no interpolation.
      w0_reg <= {1'b1, {FRAC{1'b0}}};      // = 1 << FRAC = 16384
      w1_reg <= {(FRAC+1){1'b0}};          // = 0
   end else begin
      w0_reg <= (1 << FRAC) - set_delta;
      w1_reg <= {1'b0, set_delta};
   end
end

// weights are non-negative; zero-extend to signed before the signed multiplies.
wire signed [ DWI+FRAC+1:0] q_mix = $signed({1'b0, w0_reg}) * q_flr
                                  + $signed({1'b0, w1_reg}) * q_cel;

reg  signed [ DWI-1:0]    q_samp;   // blended Q, rescaled + registered
reg  signed [ DWI-1:0]    i_reg ;   // I aligned with q_samp
always @(posedge clk_i) begin
   q_samp <= q_mix >>> FRAC;        // arithmetic (sign-preserving) shift
   i_reg  <= i_d1;
end

//---------------------------------------------------------------------------------
//  Weighted sum with the host coefficients, then rescale and saturate.
//     acc    = ci*I + cq*Q              (still scaled by 2^FRAC)
//     scaled = acc >>> FRAC             (back to 14-bit range)
//---------------------------------------------------------------------------------
//  Coefficient source select, REGISTERED.
//
//  The mux is deliberately not combinational. Putting a 2-to-1 select directly
//  in front of a multiplier input adds LUT depth to a path that already reaches
//  a DSP, and this file has lost time twice to exactly that kind of addition
//  (see FIX 6 and FIX 7 above). Registering it puts the mux between two
//  flip-flops instead, where it has a whole clock to settle, and costs only one
//  cycle of latency on a COEFFICIENT change - which is quasi-static control,
//  not datapath. The multiply below sees a register output either way.
reg signed [ DWC-1: 0] ci_use, cq_use;

always @(posedge clk_i) begin
   if (rstn_i == 1'b0) begin
      ci_use <= {DWC{1'b0}};
      cq_use <= {DWC{1'b0}};
   end else begin
      ci_use <= ext_sel_i ? $signed(ci_ext_i) : set_ci;
      cq_use <= ext_sel_i ? $signed(cq_ext_i) : set_cq;
   end
end

wire signed [ DWC+DWI-1:0]    mult_i = ci_use * i_reg ;   // 16b * 14b = 30b
wire signed [ DWC+DWI-1:0]    mult_q = cq_use * q_samp;
wire signed [ DWC+DWI  :0]    acc    = mult_i + mult_q;   // 31 bits

//---------------------------------------------------------------------------------
//  FIX 6 [Timing 38-282] - output stage split across two clock cycles.
//
//  THE PROBLEM
//  This stage used to do, all within one 8 ns clock tick:
//      multiply -> 31-bit add -> compare against two clip limits -> store
//  which measured 8.464 ns and missed by 0.639 ns. It was the last 16 failing
//  endpoints in the design. Unlike FIX 5 there was nothing to hoist out: every
//  operation here is genuine per-sample work.
//
//  THE FIX
//  Park the sum in a register, and do the clipping on the following tick. Each
//  half now fits comfortably, with real margin left over - which matters
//  because the acquisition system will be added to this device and will disturb
//  the placement.
//
//  THE COST: ONE EXTRA CLOCK OF LATENCY (8 ns).
//  The module's transport latency goes from L = 2 to L = 3 samples, so the
//  measured loop delay becomes ~128 ns instead of ~120 ns. This is a pure
//  transport delay, so it only adds a constant phase lag of
//  360*L*f_sig/f_clk degrees, which the host already cancels.
//
//  ** THE HOST MUST BE UPDATED: set L_PIPE = 3 in phase_shift_control.ipynb
//     and in validate_bram.py. If this is missed, every requested phase will
//     be wrong by 360*f_sig/f_clk degrees - 2.1 deg at 740 kHz, 115 deg at
//     40 MHz. **
//
//  Why this costs the experiment essentially nothing: the phase-versus-
//  frequency slope changes from 43.1 to 46.0 deg/MHz, i.e. 0.043 to 0.046
//  deg/kHz across the resonator; and the delay-limited feedback bandwidth,
//  roughly 1/(2*tau), moves from 4.2 MHz to 3.9 MHz - both far outside
//  anything this detection system does.
//
//  The bypass path is delayed by the same amount (i_byp) so that switching
//  bypass on and off does not change the latency.
//---------------------------------------------------------------------------------
reg signed [ DWC+DWI  :0] acc_reg;   // pipelined sum, 31 bits
reg signed [ DWI-1    :0] i_byp ;    // input aligned with acc_reg, for bypass

always @(posedge clk_i) begin
   if (rstn_i == 1'b0) begin
      acc_reg <= {(DWC+DWI+1){1'b0}};
      i_byp   <= {DWI{1'b0}};
   end else begin
      acc_reg <= acc;
      i_byp   <= i_reg;
   end
end

wire signed [ DWC+DWI-FRAC:0] scaled = acc_reg >>> FRAC;  // 17 bits

reg signed [ DWI-1:0] out_a;

// clip limits for signed 14-bit:  +8191 / -8192
localparam signed [DWI-1:0] SAT_MAX =  (1 << (DWI-1)) - 1;
localparam signed [DWI-1:0] SAT_MIN = -(1 << (DWI-1));

always @(posedge clk_i) begin
   if (rstn_i == 1'b0)         out_a <= {DWI{1'b0}};
   else if (set_byp)           out_a <= i_byp;          // bypass = input through
   else if (scaled > SAT_MAX)  out_a <= SAT_MAX;        // clip high
   else if (scaled < SAT_MIN)  out_a <= SAT_MIN;        // clip low
   else                        out_a <= scaled[DWI-1:0];// in range
end

assign dat_a_o = out_a;
assign dat_b_o = {DWI{1'b0}};       // single-channel: CH B held at zero

//---------------------------------------------------------------------------------
//  System bus - WRITE
//---------------------------------------------------------------------------------
always @(posedge clk_i) begin
   if (rstn_i == 1'b0) begin
      set_ci    <= {DWC{1'b0}};
      set_cq    <= {DWC{1'b0}};
      set_dly   <= {DLYW{1'b0}};
      set_delta <= {FRAC{1'b0}};
      set_byp   <= 1'b0;
   end else if (sys_wen) begin
      if (sys_addr[19:0]==20'h00)  set_ci    <= sys_wdata[DWC-1:0];   // A*cos(phi)
      if (sys_addr[19:0]==20'h04)  set_cq    <= sys_wdata[DWC-1:0];   // A*sin(phi)
      if (sys_addr[19:0]==20'h08)  set_dly   <= sys_wdata[DLYW-1:0];  // floor(D)
      if (sys_addr[19:0]==20'h0C)  set_delta <= sys_wdata[FRAC-1:0];  // d
      if (sys_addr[19:0]==20'h10)  set_byp   <= sys_wdata[0];         // bypass
   end
end

//---------------------------------------------------------------------------------
//  System bus - READ
//---------------------------------------------------------------------------------
wire sys_en = sys_wen | sys_ren;

always @(posedge clk_i) begin
   if (rstn_i == 1'b0) begin
      sys_err <= 1'b0;
      sys_ack <= 1'b0;
   end else begin
      sys_err <= 1'b0;
      casez (sys_addr[19:0])
         20'h00 : begin sys_ack <= sys_en; sys_rdata <= {{32-DWC {set_ci[DWC-1]}}, set_ci   }; end
         20'h04 : begin sys_ack <= sys_en; sys_rdata <= {{32-DWC {set_cq[DWC-1]}}, set_cq   }; end
         20'h08 : begin sys_ack <= sys_en; sys_rdata <= {{32-DLYW{1'b0}},          set_dly  }; end
         20'h0C : begin sys_ack <= sys_en; sys_rdata <= {{32-FRAC{1'b0}},          set_delta}; end
         20'h10 : begin sys_ack <= sys_en; sys_rdata <= {31'b0,                    set_byp  }; end
         // 0x14 READ-ONLY status. Bit 0 = 1 means set_dly was written as 0 and
         // has been clamped to 1 (see FIX 4). The host should treat a 1 here as
         // "the requested delay is invalid at this signal frequency" and pick a
         // larger equivalent delay, not ignore it.
         20'h14 : begin sys_ack <= sys_en; sys_rdata <= {31'b0,                dly_clamped }; end
         default: begin sys_ack <= sys_en; sys_rdata <= 32'h0                               ; end
      endcase
   end
end

endmodule
