/**
 * @brief Parameter sequencer - times the feedback phase in hardware.
 *
 * @Author Alex (Imperial CCM internship) - custom module
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * ===========================================================================
 *  WHAT THIS IS FOR
 * ===========================================================================
 *  Section III.B of Herkenhoff et al. describes a TIMED sequence: detune the
 *  resonator so the ion is decoupled, fire an excitation pulse that sets a
 *  starting phase, let the ion evolve for an exact duration, re-couple, and
 *  read the phase back. The measurement is only as good as the timing.
 *
 *  Stage 9 measured what software on this board can do: a 45 ms control
 *  interval, dominated by sensing and settling, with jitter to match. The
 *  fabric clock is 8 ns. Five orders of magnitude separate them, so timed
 *  switching cannot live in Python - it has to live here.
 *
 *  That is all this module is: a small state machine that rewrites the phase
 *  shifter's two coefficients at exact times, or on an external trigger edge.
 *
 * ===========================================================================
 *  WHAT IT DOES NOT TOUCH
 * ===========================================================================
 *  The feedback datapath is unchanged. The phase shifter's arithmetic is
 *  unchanged. All that was added there is a REGISTERED two-input mux on the
 *  coefficient pair, which sits between two flip-flops and therefore adds no
 *  delay to the guarded ADC -> phase-shifter path.
 *
 *  Power-on behaviour is unchanged: CTRL[2] defaults to 0, meaning the phase
 *  shifter uses its own software registers exactly as before, and the state
 *  machine sits idle. The board is bit-for-bit as it was until armed. Same
 *  discipline as the resonator and the noise sources.
 *
 * ===========================================================================
 *  REGISTER MAP  -  base address 0x40700000  (system bus slot sys[7])
 * ===========================================================================
 *  One 32-bit access at a time, as everywhere else on this bus.
 *
 *  Offset  Name       R/W  Contents
 *  ------  ---------  ---  -----------------------------------------------
 *   0x00   CTRL       RW   [0] arm - start at set 0. Self-clearing.
 *                          [1] abort - stop now, hold current coefficients.
 *                              Self-clearing.
 *                          [2] source. 0 = phase shifter uses its own
 *                              registers (default), 1 = this module drives it.
 *   0x04   STATUS     RO   [2:0] set currently being held
 *                          [3]   running
 *                          [4]   done - sequence finished and holding
 *                          [5]   trigger seen since arm (sticky)
 *   0x08   TRIG_CFG   RW   [0] edge: 0 = rising, 1 = falling
 *                          [1] enable the external trigger input
 *   0x0C   VERSION    RO   0x5E900001. A stub answers every read with zero and
 *                          looks politely dead, so software checks this before
 *                          trusting anything else - the same trap the
 *                          resonator's presence probe exists for.
 *
 *   0x10 + 16*n + 0   RW   CI       set n, A*cos(phi), signed Q2.14
 *   0x10 + 16*n + 4   RW   CQ       set n, A*sin(phi), signed Q2.14
 *   0x10 + 16*n + 8   RW   DURATION set n, clocks to hold.
 *                          0 means WAIT FOR A TRIGGER instead of counting.
 *   0x10 + 16*n + 12  RW   FLAGS    set n:
 *                            [0] pulse burst_o on entry (excitation pulse)
 *                            [1] pulse acq_arm_o on entry (coherent capture)
 *                            [2] last set in the sequence
 *                            [3] when last: loop back to set 0 instead of
 *                                holding
 *   n = 0..7, so the sets occupy 0x10 .. 0x8F.
 *
 *  Any other offset reads as zero.
 *
 * ===========================================================================
 *  TIMING RESOLUTION AND ITS LIMIT
 * ===========================================================================
 *  DURATION counts the 125 MHz fabric clock, so steps are 8 ns and the longest
 *  single step is 2^32 clocks - about 34 seconds.
 *
 *  The external trigger is synchronised through two flip-flops before its edge
 *  is detected, which is what makes it safe to bring an asynchronous signal
 *  into this clock domain. It also means the trigger is quantised to one
 *  clock: expect +-8 ns of jitter. Eliminating that needs a reference clock
 *  input, which is not wired on this build.
 *
 *  WHAT THIS MODULE CANNOT TELL YOU: whether the 125 MHz clock is itself
 *  correct. Everything here is counted in units of that clock, so a clock that
 *  is wrong produces durations that are wrong by the same fraction, silently.
 *  See Test Stage 14a.
 */

`timescale 1ns / 1ps

module red_pitaya_sequencer #(
  parameter integer DWC  = 16,   // coefficient width, matches the phase shifter
  parameter integer NSET = 8     // number of parameter sets (must be a power of 2)
)(
  // ---- clock and reset ----
  input                      clk_i     ,  //!< 125 MHz processing clock
  input                      rstn_i    ,  //!< active-LOW synchronous reset

  // ---- to the phase shifter ----
  output     [ DWC-1: 0]     ci_o      ,  //!< coefficient pair for the current set
  output     [ DWC-1: 0]     cq_o      ,
  output                     sel_o     ,  //!< 1 = phase shifter should use them

  // ---- pulses at set entry (one clock wide) ----
  output reg                 burst_o   ,  //!< fire the excitation pulse
  output reg                 acq_arm_o ,  //!< start a coherent capture

  // ---- external trigger ----
  input                      trig_i    ,  //!< asynchronous; synchronised inside

  // ---- system bus ----
  input      [ 32-1: 0]      sys_addr  ,
  input      [ 32-1: 0]      sys_wdata ,
  input                      sys_wen   ,
  input                      sys_ren   ,
  output reg [ 32-1: 0]      sys_rdata ,
  output reg                 sys_err   ,
  output reg                 sys_ack
);

localparam integer SW = 3;                       // log2(NSET)
localparam [31:0]  VERSION = 32'h5E900001;

//---------------------------------------------------------------------------------
//  Software-written configuration
//---------------------------------------------------------------------------------
reg                    set_arm;
reg                    set_abort;
reg                    set_source;
reg                    set_trig_edge;
reg                    set_trig_en;

reg  signed [DWC-1:0]  mem_ci   [0:NSET-1];
reg  signed [DWC-1:0]  mem_cq   [0:NSET-1];
reg         [31:0]     mem_dur  [0:NSET-1];
reg         [3:0]      mem_flag [0:NSET-1];

//---------------------------------------------------------------------------------
//  Trigger: two flip-flops to cross into this clock domain, then an edge.
//
//  Sampling an asynchronous signal straight into logic can leave a flip-flop
//  midway between 0 and 1 for a while, and anything reading it during that time
//  can disagree about what it saw. Two stages give it a whole clock to settle.
//---------------------------------------------------------------------------------
reg [2:0] trig_sync;
always @(posedge clk_i) begin
  if (rstn_i == 1'b0) trig_sync <= 3'b000;
  else                trig_sync <= {trig_sync[1:0], trig_i};
end

wire trig_rise =  trig_sync[1] & ~trig_sync[2];
wire trig_fall = ~trig_sync[1] &  trig_sync[2];
wire trig_edge = set_trig_en & (set_trig_edge ? trig_fall : trig_rise);

//---------------------------------------------------------------------------------
//  The sequence itself
//---------------------------------------------------------------------------------
localparam [1:0] S_IDLE = 2'd0,
                 S_HOLD = 2'd1,    // counting down, or waiting for a trigger
                 S_DONE = 2'd2;

reg [1:0]      state;
reg [SW-1:0]   cur;
reg [31:0]     cnt;
reg            trig_seen;

wire [3:0] flags_cur = mem_flag[cur];
wire       waiting   = (mem_dur[cur] == 32'd0);   // 0 duration = wait for trigger
wire       expired   = waiting ? trig_edge : (cnt == 32'd0);
wire       last_set  = flags_cur[2];
wire       do_loop   = flags_cur[3];

assign ci_o  = mem_ci[cur];
assign cq_o  = mem_cq[cur];
assign sel_o = set_source;

// Entering a set pulses whichever of the two outputs its flags ask for. Held
// to exactly one clock so downstream sees an edge, not a level.
task enter_set(input [SW-1:0] n);
  begin
    cur       <= n;
    cnt       <= mem_dur[n];
    burst_o   <= mem_flag[n][0];
    acq_arm_o <= mem_flag[n][1];
  end
endtask

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    state     <= S_IDLE;
    cur       <= {SW{1'b0}};
    cnt       <= 32'd0;
    trig_seen <= 1'b0;
    burst_o   <= 1'b0;
    acq_arm_o <= 1'b0;
  end else begin
    burst_o   <= 1'b0;                 // one clock wide unless re-asserted below
    acq_arm_o <= 1'b0;

    if (trig_edge) trig_seen <= 1'b1;

    if (set_abort) begin
      state <= S_DONE;                 // stop, hold whatever is loaded
    end else begin
      case (state)
        S_IDLE: begin
          if (set_arm) begin
            trig_seen <= 1'b0;
            enter_set({SW{1'b0}});
            state     <= S_HOLD;
          end
        end

        S_HOLD: begin
          if (!waiting && cnt != 32'd0)
            cnt <= cnt - 32'd1;
          if (expired) begin
            if (last_set) begin
              if (do_loop) begin
                enter_set({SW{1'b0}});
              end else begin
                state <= S_DONE;       // hold the final coefficients
              end
            end else begin
              enter_set(cur + 1'b1);
            end
          end
        end

        S_DONE: begin
          if (set_arm) begin           // re-arm without a reset
            trig_seen <= 1'b0;
            enter_set({SW{1'b0}});
            state     <= S_HOLD;
          end
        end

        default: state <= S_IDLE;
      endcase
    end
  end
end

//---------------------------------------------------------------------------------
//  System bus
//---------------------------------------------------------------------------------
integer k;
wire [SW-1:0] a_set  = sys_addr[SW+3:4];      // which set   (0x10 steps of 16)
wire [1:0]    a_word = sys_addr[3:2];         // which word within it
wire          a_is_set = (sys_addr[19:0] >= 20'h10) && (sys_addr[19:0] < 20'h10 + 16*NSET);

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    set_arm       <= 1'b0;
    set_abort     <= 1'b0;
    set_source    <= 1'b0;             // phase shifter keeps its own registers
    set_trig_edge <= 1'b0;
    set_trig_en   <= 1'b0;
    for (k = 0; k < NSET; k = k + 1) begin
      mem_ci[k]   <= {DWC{1'b0}};
      mem_cq[k]   <= {DWC{1'b0}};
      mem_dur[k]  <= 32'd0;
      mem_flag[k] <= 4'd0;
    end
  end else begin
    set_arm   <= 1'b0;                 // both are one-shot
    set_abort <= 1'b0;
    if (sys_wen) begin
      if (sys_addr[19:0] == 20'h00) begin
        set_arm    <= sys_wdata[0];
        set_abort  <= sys_wdata[1];
        set_source <= sys_wdata[2];
      end
      if (sys_addr[19:0] == 20'h08) begin
        set_trig_edge <= sys_wdata[0];
        set_trig_en   <= sys_wdata[1];
      end
      if (a_is_set) begin
        case (a_word)
          2'd0: mem_ci[a_set]   <= sys_wdata[DWC-1:0];
          2'd1: mem_cq[a_set]   <= sys_wdata[DWC-1:0];
          2'd2: mem_dur[a_set]  <= sys_wdata;
          2'd3: mem_flag[a_set] <= sys_wdata[3:0];
        endcase
      end
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
    if (a_is_set) begin
      case (a_word)
        2'd0: sys_rdata <= {{(32-DWC){mem_ci[a_set][DWC-1]}}, mem_ci[a_set]};
        2'd1: sys_rdata <= {{(32-DWC){mem_cq[a_set][DWC-1]}}, mem_cq[a_set]};
        2'd2: sys_rdata <= mem_dur[a_set];
        2'd3: sys_rdata <= {28'h0, mem_flag[a_set]};
      endcase
    end else begin
      case (sys_addr[19:0])
        20'h00 : sys_rdata <= {29'h0, set_source, 2'b00};
        20'h04 : sys_rdata <= {26'h0, trig_seen, (state == S_DONE),
                                      (state == S_HOLD), cur};
        20'h08 : sys_rdata <= {30'h0, set_trig_en, set_trig_edge};
        20'h0C : sys_rdata <= VERSION;
        default: sys_rdata <= 32'h0;
      endcase
    end
  end
end

endmodule
