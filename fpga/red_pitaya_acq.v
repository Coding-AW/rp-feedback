/**
 * @brief Acquisition system top level - wires the signal chain together and
 *        provides the software interface.
 *
 * Project-specific acquisition module.
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * Reproduces the acquisition system of Herkenhoff et al., "A digital feedback
 * system for advanced ion manipulation techniques in Penning traps",
 * Rev. Sci. Instrum. 92, 103201 (2021) - the blue-outlined blocks of Fig. 6a.
 *
 * ===========================================================================
 *  WHAT IS HERE, AND WHAT IS NOT (yet)
 * ===========================================================================
 *  Present:
 *      ADC tap -> IQ mixer -> CIC decimators -> peek registers / scope tap
 *
 *  Still to come (see docs/acquisition.md):
 *      -> FIR droop corrector -> 64-bit packing -> FIFO -> DMA -> DDR
 *
 *  The chain is deliberately usable BEFORE the memory path exists. The peek
 *  registers and the scope tap let the mixer and the decimator be tested on
 *  real hardware now (test-plan stages 2, 3 and 4), rather than waiting until
 *  every block is written and then debugging all of them at once.
 *
 * ===========================================================================
 *  RELATIONSHIP TO THE FEEDBACK PATH - READ THIS BEFORE EDITING
 * ===========================================================================
 *  This module only ever READS the digitised ADC samples. It does not sit in
 *  the feedback loop and must never be allowed to. The feedback path
 *  (red_pitaya_phaseshift) is latency-critical - it has been characterised at
 *  119.87 ns and every clock cycle of delay becomes a phase error at the ion.
 *  This module's latency is irrelevant by comparison, because nothing it
 *  produces goes back into the trap.
 *
 *  Concretely: `dat_a_i` and `dat_b_i` are fan-outs of nets that already exist.
 *  Adding a reader to a net costs no time. If you ever find yourself putting
 *  logic BETWEEN the ADC and the phase shifter, stop - that is the one change
 *  that would undo the timing work done in stage 1.
 *
 * ===========================================================================
 *  REGISTER MAP  -  base address 0x40600000  (system bus slot sys[6])
 * ===========================================================================
 *  All registers are 32 bits and MUST be accessed one 32-bit word at a time.
 *  A bulk mmap slice from Python becomes a burst transfer that the GP-AXI to
 *  system-bus bridge cannot acknowledge; it locks the bus and reboots the
 *  board. (Same rule as the phase shifter - see docs/feedback.md.)
 *
 *  Offset  Name        R/W  Contents
 *  ------  ----------  ---  ----------------------------------------------------
 *   0x00   CTRL        RW   [0] enable      1 = run, 0 = hold the chain in reset
 *                           [1] soft reset  write 1 to pulse; self-clearing
 *                           [2] test mode   1 = replace data with a counter
 *                           [3] scope tap   1 = send internals to the scope
 *                           [4] arm         1 = write samples into memory
 *                           [5] wrap        1 = overwrite oldest at region end
 *                                           0 = stop at the end (single capture)
 *                           [6] fir bypass  1 = skip the droop correction
 *                           [7] dma clear   write 1 to flush; self-clearing
 *                           [8] axi port    0 = axi0 (default), 1 = axi1.
 *                                           Which of the processor's two memory
 *                                           ports the writer uses. Exists so the
 *                                           two can be compared with a register
 *                                           write instead of a 25-minute rebuild.
 *                                           USE axi0 on this board: the boot
 *                                           software leaves axi1's port half
 *                                           configured and it drops the upper
 *                                           32 bits (Q) of every sample. See
 *                                           CHANGELOG.md 2026-07-30
 *   0x04   LO_FINC     RW   [31:0] local-oscillator frequency word
 *                           finc = round(f_lo / 125e6 * 2^32)
 *                           step 0.0291 Hz; 40 MHz -> 1374389535
 *   0x08   DEC_LOG2    RW   [3:0]  log2 of the decimation factor, 6..12
 *                           6 -> R=64 ... 12 -> R=4096
 *   0x0C   SRC_SEL     RW   [0]    0 = input IN1 (default), 1 = input IN2
 *   0x10   TAP_SEL     RW   [1:0]  what the scope tap shows:
 *                                    0 = mixer output      (every clock)
 *                                    1 = decimator output  (every R clocks)
 *                                    2 = corrector output  (every R clocks)
 *   0x14   TAP_SHIFT   RW   [4:0]  which 14-bit window of the tapped value to
 *                                  send to the scope, counting up from bit 0
 *   0x18   PEEK_I      RO   [31:0] most recent I sample
 *   0x1C   PEEK_Q      RO   [31:0] most recent Q sample
 *   0x20   SAMPLE_CNT  RO   [31:0] output samples produced since the last reset
 *   0x24   STATUS      RO   [0] enabled  [1] test mode  [2] scope tap active
 *   0x28   MEM_START   RW   first address of the memory region
 *   0x2C   MEM_STOP    RW   LAST address of the region - INCLUSIVE, not one
 *                           past the end. The writer may write the 8-byte word
 *                           AT this address, after which MEM_CUR reads
 *                           MEM_STOP + 8. Set it to first + size - 8, or the
 *                           writer is authorised to touch 8 bytes beyond what
 *                           you intended.
 *   0x30   MEM_CUR     RO   address currently being written
 *   0x34   DMA_COUNT   RO   samples handed to the memory writer since the clear
 *   0x38   STATUS2     RO   [0] memory overflow - SAMPLES WERE LOST
 *                           [1] filter overrun  - decimation too small
 *                           [2] filter bypassed - correction not applied
 *                           [3] WRITE ERROR - memory REFUSED a write. Sticky.
 *                               Distinguishes "the writes were accepted" from
 *                               "the writes succeeded", which every other signal
 *                               here conflates
 *   0x40   COEF_ADDR   RW   which correction-filter coefficient to access
 *   0x44   COEF_DATA   RW   write: store a coefficient at COEF_ADDR
 *                           read : what the chip currently holds there
 *   0x48   BUILD_ID    RO   [31:0] hash of the Verilog this bitstream was built
 *                           from. Answers "is this chip running the source I am
 *                           editing?" - a question file dates cannot answer,
 *                           because a bitstream can be freshly written and still
 *                           contain week-old logic. 0 = not built by
 *                           project.ps1 build. See build_id.vh.
 *
 *  The correction filter's coefficients can be REWRITTEN AT RUN TIME through
 *  0x40 and 0x44 - no rebuild, no new bitstream. Disable the chain first
 *  (CTRL = 0), write all of them, then reset and enable: a pass takes 155 clocks
 *  and reads the memory throughout, so changing it midway mixes two filters.
 *  See notebooks/acquisition/fir_filter_designer.ipynb.
 *
 *  Any other offset reads as zero.
 *
 *  MEMORY REGION WARNING: the writer puts data at whatever physical address it
 *  is given. It must be a region Linux has been told not to use, or it will
 *  overwrite the operating system. See red_pitaya_acq_dma.v.
 *
 * ===========================================================================
 *  THE THREE DEBUG FEATURES, AND WHY EACH EXISTS
 * ===========================================================================
 *  1. TEST-PATTERN MODE (CTRL[2])
 *     Replaces the real I and Q with a simple counting sequence:
 *         I = n,  Q = ~n   (bitwise complement)
 *     so that I + Q == 0xFFFFFFFF for every sample, always.
 *
 *     Once the memory path exists this is the fastest possible check that the
 *     transport is sound: if what lands in memory is an unbroken count, every
 *     sample arrived, in order, undamaged. Each fault has its own signature -
 *     gaps mean dropped samples, repeats mean a stall, and the I+Q invariant
 *     failing means the two halves of the 64-bit word have been swapped.
 *     Debugging data movement with real signals instead is miserable, because
 *     you cannot tell a transport fault from a signal-processing fault.
 *
 *  2. PEEK REGISTERS (0x18, 0x1C)
 *     The most recent output sample, readable directly by the processor. This
 *     makes the mixer and decimator testable long before the memory path is
 *     built. Reading them is slow and irregular, so they are for checking
 *     values, not for capturing waveforms.
 *
 *  3. SCOPE TAP (CTRL[3], TAP_SEL, TAP_SHIFT)
 *     Substitutes an internal signal for the scope's normal inputs, so the
 *     existing Red Pitaya scope - and the notebook that already works with it -
 *     can capture 16384 consecutive samples of any point in the chain. Best
 *     value per gate of anything here: no new capture hardware at all.
 *
 *     Note when tapping the CIC output: it only changes once every R clocks,
 *     while the scope samples every clock. At R = 1024 a 16384-sample capture
 *     holds just 16 distinct values. Use a small decimation factor when looking
 *     at the CIC through the scope, or tap the mixer instead.
 */

`timescale 1ns / 1ps

module red_pitaya_acq #(
  parameter integer DWI    = 14,   // ADC sample width
  parameter integer DWL    = 16,   // local-oscillator width
  parameter integer DWM    = 24,   // mixer output width  (paper: 24)
  parameter integer DWC    = 32,   // CIC output width    (paper: 32)
  parameter integer PACCW  = 32,   // DDS phase accumulator width
  parameter integer LUTW   = 12,   // DDS sine table address width
  parameter integer NSTAGE = 4,    // CIC stages
  parameter integer LMAX   = 12    // largest log2(decimation)
)(
  // ---- clock and reset ----
  input                     clk_i     ,  //!< 125 MHz processing clock (adc_clk)
  input                     rstn_i    ,  //!< active-LOW system reset

  // ---- tapped ADC inputs (read-only fan-out; adds no delay to the feedback path)
  input      [ DWI-1: 0]    dat_a_i   ,  //!< digitised IN1
  input      [ DWI-1: 0]    dat_b_i   ,  //!< digitised IN2

  // ---- scope tap: substituted for the scope's inputs when tap_en_o is high ----
  output     [ DWI-1: 0]    tap_a_o   ,  //!< to scope channel A
  output     [ DWI-1: 0]    tap_b_o   ,  //!< to scope channel B
  output                    tap_en_o  ,  //!< 1 = scope should use the tap

  // ---- decimated, corrected output stream (also fed to the memory writer) ----
  output     [ DWC-1: 0]    out_i_o   ,  //!< I, valid when out_stb_o is high
  output     [ DWC-1: 0]    out_q_o   ,  //!< Q, valid when out_stb_o is high
  output                    out_stb_o ,  //!< one clock high per output sample

  // ---- connection to a memory-write master in red_pitaya_ps ----
  //      This design uses axi1, the port the stock oscilloscope left unused.
  output                    axi_clk_o   ,
  output                    axi_rstn_o  ,
  output     [ 32-1: 0]     axi_waddr_o ,
  output     [ 64-1: 0]     axi_wdata_o ,
  output     [  8-1: 0]     axi_wsel_o  ,
  output                    axi_wvalid_o,
  output     [  4-1: 0]     axi_wlen_o  ,
  output                    axi_wfixed_o,
  output                    axi_sel_o   ,  //!< CTRL[8]: 0 = axi0, 1 = axi1
  input                     axi_werr_i  ,
  input                     axi_wrdy_i  ,

  // ---- system bus ----
  input      [ 32-1: 0]     sys_addr  ,
  input      [ 32-1: 0]     sys_wdata ,
  input                     sys_wen   ,
  input                     sys_ren   ,
  output reg [ 32-1: 0]     sys_rdata ,
  output reg                sys_err   ,
  output reg                sys_ack
);

//=================================================================================
//  SECTION 1 - Configuration registers written by software
//=================================================================================
reg  [ PACCW-1: 0] set_finc     ;   // 0x04 local-oscillator frequency word
reg  [    4-1: 0]  set_dec_log2 ;   // 0x08 log2 of the decimation factor
reg                set_src      ;   // 0x0C input select: 0 = IN1, 1 = IN2
reg  [    2-1: 0]  set_tap_sel  ;   // 0x10 scope tap source
reg  [    5-1: 0]  set_tap_shift;   // 0x14 scope tap bit window
reg                set_ena      ;   // 0x00[0] enable
reg                set_test     ;   // 0x00[2] test-pattern mode
reg                set_tap_en   ;   // 0x00[3] scope tap enable
reg                soft_rst     ;   // 0x00[1] self-clearing reset pulse
reg                set_arm      ;   // 0x00[4] write samples to memory
reg                set_wrap     ;   // 0x00[5] wrap at the end of the region
reg                set_fir_byp  ;   // 0x00[6] bypass the correction filter
reg                set_axi_sel  ;   // 0x00[8] which memory port to write through
reg                dma_clr      ;   // 0x00[7] self-clearing: flush the memory writer
reg  [ 32-1: 0]    set_mem_start;   // 0x28 first address of the memory region
reg  [ 32-1: 0]    set_mem_stop ;   // 0x2C last  address of the memory region
reg  [  9-1: 0]    coef_addr    ;   // 0x40 which filter coefficient
reg  [ 18-1: 0]    coef_wdata   ;   // 0x44 value to write there
reg                coef_we      ;   // set for one clock by a write to 0x44

//---------------------------------------------------------------------------------
//  Internal reset.
//
//  The chain is held in reset whenever it is disabled or a soft reset is
//  requested. This matters more than it might appear: the CIC integrators hold
//  a running total that assumes one fixed decimation factor. Changing the
//  factor mid-stream leaves a meaningless partial sum in the pipeline and
//  produces a burst of nonsense. The intended sequence from software is
//  therefore always:
//        disable -> change settings -> soft reset -> enable
//---------------------------------------------------------------------------------
wire acq_rstn = rstn_i & set_ena & ~soft_rst;

//=================================================================================
//  SECTION 2 - Input selection
//
//  A plain multiplexer choosing which digitised input feeds the chain. This is
//  a READ of an existing net - it does not interrupt or delay anything.
//=================================================================================
wire signed [ DWI-1: 0] src_dat = set_src ? dat_b_i : dat_a_i;

//=================================================================================
//  SECTION 3 - Local oscillator (block 0)
//=================================================================================
wire signed [ DWL-1: 0] lo_cos;
wire signed [ DWL-1: 0] lo_sin;

// Restart the oscillator's phase from zero whenever the chain is reset, so that
// a capture always begins at a known, repeatable phase. Without this, the
// starting phase would depend on however long the board had been powered up.
reg phase_rst;
always @(posedge clk_i) phase_rst <= ~acq_rstn;

red_pitaya_acq_dds #(
  .PACCW (PACCW),
  .LUTW  (LUTW ),
  .DWO   (DWL  )
) i_dds (
  .clk_i       (clk_i     ),
  .rstn_i      (acq_rstn  ),
  .set_finc_i  (set_finc  ),
  .phase_rst_i (phase_rst ),
  .lo_cos_o    (lo_cos    ),
  .lo_sin_o    (lo_sin    )
);

//=================================================================================
//  SECTION 4 - IQ mixer (block 1)
//=================================================================================
wire signed [ DWM-1: 0] mix_i;
wire signed [ DWM-1: 0] mix_q;

red_pitaya_acq_mixer #(
  .DWI   (DWI),
  .DWL   (DWL),
  .DWO   (DWM),
  .SHIFT (6  )
) i_mixer (
  .clk_i    (clk_i   ),
  .rstn_i   (acq_rstn),
  .dat_i    (src_dat ),
  .lo_cos_i (lo_cos  ),
  .lo_sin_i (lo_sin  ),
  .i_dat_o  (mix_i   ),
  .q_dat_o  (mix_q   )
);

//=================================================================================
//  SECTION 5 - Decimation strobe
//
//  One pulse every R clocks, where R = 2^set_dec_log2. Both CIC filters are
//  driven from this single strobe so that the I and Q channels are guaranteed
//  to sample at exactly the same instants. If they ever drifted apart by even
//  one clock the complex signal would acquire a spurious phase rotation.
//
//  The counter is 13 bits, enough for the largest decimation factor of 4096.
//=================================================================================
reg  [ LMAX: 0] dec_cnt;
wire [ LMAX: 0] dec_max = ({{LMAX{1'b0}}, 1'b1} << set_dec_log2) - 1'b1;  // R - 1
wire            dec_stb = (dec_cnt == dec_max);

always @(posedge clk_i) begin
  if (acq_rstn == 1'b0)   dec_cnt <= {(LMAX+1){1'b0}};
  else if (dec_stb)       dec_cnt <= {(LMAX+1){1'b0}};
  else                    dec_cnt <= dec_cnt + 1'b1;
end

//=================================================================================
//  SECTION 6 - CIC decimators (block 2), one per channel
//=================================================================================
wire signed [ DWC-1: 0] cic_i, cic_q;
wire                    cic_stb_i, cic_stb_q;

red_pitaya_acq_cic #(
  .DWI (DWM), .DWO (DWC), .NSTAGE (NSTAGE), .LMAX (LMAX)
) i_cic_i (
  .clk_i          (clk_i       ),
  .rstn_i         (acq_rstn    ),
  .set_dec_log2_i (set_dec_log2),
  .stb_i          (dec_stb     ),
  .dat_i          (mix_i       ),
  .dat_o          (cic_i       ),
  .stb_o          (cic_stb_i   )
);

red_pitaya_acq_cic #(
  .DWI (DWM), .DWO (DWC), .NSTAGE (NSTAGE), .LMAX (LMAX)
) i_cic_q (
  .clk_i          (clk_i       ),
  .rstn_i         (acq_rstn    ),
  .set_dec_log2_i (set_dec_log2),
  .stb_i          (dec_stb     ),
  .dat_i          (mix_q       ),
  .dat_o          (cic_q       ),
  .stb_o          (cic_stb_q   )
);

// The two filters are identical and share a strobe, so cic_stb_i and cic_stb_q
// are the same signal by construction. Only one is used; the other is left
// connected purely so the port is not dangling and the intent stays obvious.
wire cic_stb = cic_stb_i;

//=================================================================================
//  SECTION 6b - Droop correction (block 3), one filter per channel
//
//  WHY IT IS SOMETIMES BYPASSED
//  The filter reuses a single multiplier 155 times per output sample, so it
//  needs about 160 clock cycles between samples. That is fine from decimation
//  256 upwards, but at 64 or 128 the next sample would arrive before it
//  finished. Below 256 the filter is therefore switched out of the path
//  automatically, and the decimator's output is used directly.
//
//  Software can also force the bypass (CTRL[6]) - which is exactly what Test
//  Stage 5 does, to measure the droop with the correction off and then on.
//
//  Both filters share the same decision, so I and Q are always treated
//  identically. If they were not, the complex signal would acquire a spurious
//  phase shift that varied across the band.
//=================================================================================
//  The threshold is NOT written out by hand: it comes from the same generated
//  file the filter itself uses, so changing the number of taps updates it
//  automatically. Getting this wrong the other way - allowing a decimation the
//  filter cannot keep up with - produces garbage that looks like data.
`include "fir_params.vh"

//  Build fingerprint - a hash of the acquisition system's Verilog sources,
//  generated by project.ps1 build and readable at 0x48. See build_id.vh for
//  why this exists.
`include "build_id.vh"

wire fir_auto_byp = (set_dec_log2 < GEN_MIN_DEC_LOG2[3:0]);
wire fir_bypass   = set_fir_byp | fir_auto_byp;

wire signed [ DWC-1: 0] fir_i, fir_q;
wire                    fir_stb_i, fir_stb_q;
wire                    fir_ovr_i, fir_ovr_q;

//  Both filters receive the SAME coefficient writes, so I and Q can never end up
//  with different filters - which would give the complex signal a spurious phase
//  shift that varied across the band, and would be very hard to spot.
//
//  Readback comes from the I filter. Since both share the write port they cannot
//  diverge, so checking one checks both.
wire [17:0] coef_rdata;

red_pitaya_acq_fir i_fir_i (
  .clk_i        (clk_i     ),
  .rstn_i       (acq_rstn  ),
  .dat_i        (cic_i     ),
  .stb_i        (cic_stb   ),
  .dat_o        (fir_i     ),
  .stb_o        (fir_stb_i ),
  .overrun_o    (fir_ovr_i ),
  .coef_addr_i  (coef_addr ),
  .coef_wdata_i (coef_wdata),
  .coef_we_i    (coef_we   ),
  .coef_rdata_o (coef_rdata)
);

red_pitaya_acq_fir i_fir_q (
  .clk_i        (clk_i     ),
  .rstn_i       (acq_rstn  ),
  .dat_i        (cic_q     ),
  .stb_i        (cic_stb   ),
  .dat_o        (fir_q     ),
  .stb_o        (fir_stb_q ),
  .overrun_o    (fir_ovr_q ),
  .coef_addr_i  (coef_addr ),
  .coef_wdata_i (coef_wdata),
  .coef_we_i    (coef_we   ),
  .coef_rdata_o (          )   // identical to the I filter's, by construction
);

// Choose between the corrected and uncorrected streams. The strobe must be
// switched along with the data: the corrected sample appears about 160 clock
// cycles after the uncorrected one, so pairing one stream's data with the
// other's strobe would capture the previous sample every time.
wire signed [ DWC-1: 0] chain_i   = fir_bypass ? cic_i   : fir_i;
wire signed [ DWC-1: 0] chain_q   = fir_bypass ? cic_q   : fir_q;
wire                    chain_stb = fir_bypass ? cic_stb : fir_stb_i;

//=================================================================================
//  SECTION 7 - Test-pattern generator (debug feature 1)
//
//  I = n, Q = ~n. The complement gives a check that holds for every sample:
//        I + Q  ==  0xFFFFFFFF
//  If that ever fails, the two halves of the 64-bit word have been swapped or
//  corrupted - a fault that a plain "both halves count up" pattern would miss.
//=================================================================================
reg [ DWC-1: 0] test_cnt;

always @(posedge clk_i) begin
  if (acq_rstn == 1'b0)  test_cnt <= {DWC{1'b0}};
  else if (chain_stb)    test_cnt <= test_cnt + 1'b1;
end

//=================================================================================
//  SECTION 8 - Output stream
//
//  This is the point the FIR corrector and the FIFO will attach to. Until they
//  exist it feeds the peek registers and the sample counter.
//=================================================================================
assign out_i_o   = set_test ?  test_cnt : chain_i;
assign out_q_o   = set_test ? ~test_cnt : chain_q;
assign out_stb_o = chain_stb;

//=================================================================================
//  SECTION 8b - Streaming to memory (block 4)
//
//  Takes the same stream the peek registers see, so what lands in memory is
//  exactly what those registers report - including the test pattern, which is
//  the point: it lets the transport be checked without any signal at all.
//=================================================================================
wire           dma_overflow;
wire           dma_werr;
assign axi_sel_o = set_axi_sel;
wire [ 32-1:0] dma_cur_addr;
wire [ 32-1:0] dma_count;

red_pitaya_acq_dma #(
  .DW (DWC),
  .AW (32 )
) i_dma (
  .clk_i           (clk_i        ),
  .rstn_i          (rstn_i       ),   // NOT acq_rstn: the memory writer must keep
                                      // its state while the chain is reconfigured
  .dat_i_i         (out_i_o      ),
  .dat_q_i         (out_q_o      ),
  .stb_i           (out_stb_o    ),
  .arm_i           (set_arm      ),
  .set_start_i     (set_mem_start),
  .set_stop_i      (set_mem_stop ),
  .set_wrap_i      (set_wrap     ),
  .clr_i           (dma_clr      ),
  .stat_overflow_o (dma_overflow ),
  .stat_werr_o     (dma_werr     ),
  .stat_cur_addr_o (dma_cur_addr ),
  .stat_count_o    (dma_count    ),
  .axi_clk_o       (axi_clk_o    ),
  .axi_rstn_o      (axi_rstn_o   ),
  .axi_waddr_o     (axi_waddr_o  ),
  .axi_wdata_o     (axi_wdata_o  ),
  .axi_wsel_o      (axi_wsel_o   ),
  .axi_wvalid_o    (axi_wvalid_o ),
  .axi_wlen_o      (axi_wlen_o   ),
  .axi_wfixed_o    (axi_wfixed_o ),
  .axi_werr_i      (axi_werr_i   ),
  .axi_wrdy_i      (axi_wrdy_i   )
);

//=================================================================================
//  SECTION 9 - Peek registers and sample counter (debug feature 2)
//=================================================================================
reg [ DWC-1: 0] peek_i, peek_q;
reg [ 32-1: 0]  sample_cnt;

always @(posedge clk_i) begin
  if (acq_rstn == 1'b0) begin
    peek_i     <= {DWC{1'b0}};
    peek_q     <= {DWC{1'b0}};
    sample_cnt <= 32'h0;
  end else if (out_stb_o) begin
    peek_i     <= out_i_o;
    peek_q     <= out_q_o;
    sample_cnt <= sample_cnt + 1'b1;
  end
end

//=================================================================================
//  SECTION 10 - Scope tap (debug feature 3)
//
//  Both candidate sources are sign-extended to a common 32 bits first, so a
//  single windowing expression serves both. Sign extension - copying the sign
//  bit leftwards - is what preserves the value of a negative number when it is
//  widened; zero-padding instead would turn every negative sample into a large
//  positive one.
//
//  The shift is clamped so that the 14-bit window can never run off the top of
//  the 32-bit value. Reading past the end would return undefined bits, which is
//  precisely the kind of fault that looks like noise in the data.
//=================================================================================
//  TAP_SEL chooses the point in the chain:
//      0 = mixer output      (updates every clock)
//      1 = decimator output  (updates every R clocks)
//      2 = corrector output  (updates every R clocks, correction applied)
//
//  Selecting 1 and then 2 with the same signal is how Test Stage 5 measures the
//  droop before and after correction.
//  SIGN EXTENSION - note how this is done, and why not the obvious way.
//
//  The obvious way is an explicit replication of the sign bit:
//
//      {{(32-DWC){cic_i[DWC-1]}}, cic_i}
//
//  but DWC is already 32, so that asks for ZERO copies of the sign bit and
//  Vivado reports "[Synth 8-693] zero replication count - replication ignored".
//  The result happens to be right, but the construct is fragile: it only works
//  because the tool quietly discards the empty part.
//
//  Assigning a SIGNED value to a wider SIGNED wire sign-extends automatically,
//  by the language's own rules, whatever the widths are. It is shorter, it
//  cannot produce a zero-width replication, and it keeps working if any of the
//  datapath widths are ever changed.
wire signed [ 32-1: 0] ext_mix_i = mix_i;   // 24 bits -> 32, sign-extended
wire signed [ 32-1: 0] ext_cic_i = cic_i;   // already 32, no change
wire signed [ 32-1: 0] ext_fir_i = fir_i;
wire signed [ 32-1: 0] ext_mix_q = mix_q;
wire signed [ 32-1: 0] ext_cic_q = cic_q;
wire signed [ 32-1: 0] ext_fir_q = fir_q;

wire signed [ 32-1: 0] tap_src_i = (set_tap_sel == 2'd2) ? ext_fir_i :
                                   (set_tap_sel == 2'd1) ? ext_cic_i :
                                                           ext_mix_i;

wire signed [ 32-1: 0] tap_src_q = (set_tap_sel == 2'd2) ? ext_fir_q :
                                   (set_tap_sel == 2'd1) ? ext_cic_q :
                                                           ext_mix_q;

localparam integer TAP_SHIFT_MAX = 32 - DWI;   // = 18

wire [ 5-1: 0] tap_shift = (set_tap_shift > TAP_SHIFT_MAX[4:0])
                         ? TAP_SHIFT_MAX[4:0] : set_tap_shift;

assign tap_a_o  = tap_src_i[tap_shift +: DWI];
assign tap_b_o  = tap_src_q[tap_shift +: DWI];
assign tap_en_o = set_tap_en;

//=================================================================================
//  SECTION 11 - System bus, write side
//
//  Runs on the same clock as the datapath, so no clock-domain crossing is
//  needed - the same arrangement red_pitaya_phaseshift uses.
//=================================================================================
always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    set_ena       <= 1'b0;               // start disabled: nothing runs until
    set_test      <= 1'b0;               // software explicitly asks for it
    set_tap_en    <= 1'b0;
    soft_rst      <= 1'b0;
    set_finc      <= {PACCW{1'b0}};
    set_dec_log2  <= 4'd10;              // R = 1024, a sensible middle default
    set_src       <= 1'b0;               // IN1
    set_tap_sel   <= 2'd0;               // mixer output
    set_tap_shift <= 5'd10;
    set_arm       <= 1'b0;               // not writing to memory
    set_wrap      <= 1'b1;               // continuous recording by default
    set_fir_byp   <= 1'b0;               // correction on where possible
    // axi0 by default (changed from axi1, 2026-07-30). The two ports are
    // identical in this design, but NOT in the processor: the boot software
    // on this board leaves axi1's port (HP1) with a channel in 32-bit mode,
    // which silently keeps the lower half of every 64-bit sample and drops
    // the upper - I arrives, Q never does. Confirmed on hardware, and that
    // setting cannot be corrected from Linux here (the write is refused).
    // axi0's port is left correctly configured, so it is the safe default.
    // axi1 remains selectable through CTRL[8] for diagnostics.
    set_axi_sel   <= 1'b0;
    dma_clr       <= 1'b0;
    set_mem_start <= 32'h0;              // software MUST set a safe region
    set_mem_stop  <= 32'h0;              // before arming
    coef_addr     <= 9'h0;
    coef_wdata    <= 18'h0;
    coef_we       <= 1'b0;
  end else begin
    // soft_rst and dma_clr are one-shots: set by a write, cleared on the next
    // clock, so software never has to remember to clear them.
    soft_rst <= 1'b0;
    dma_clr  <= 1'b0;
    coef_we  <= 1'b0;          // one-shot: a write to 0x44 stores one coefficient

    if (sys_wen) begin
      if (sys_addr[19:0] == 20'h00) begin
        set_ena     <= sys_wdata[0];
        soft_rst    <= sys_wdata[1];
        set_test    <= sys_wdata[2];
        set_tap_en  <= sys_wdata[3];
        set_arm     <= sys_wdata[4];
        set_wrap    <= sys_wdata[5];
        set_fir_byp <= sys_wdata[6];
        set_axi_sel <= sys_wdata[8];
        dma_clr     <= sys_wdata[7];
      end
      if (sys_addr[19:0] == 20'h04) set_finc      <= sys_wdata[PACCW-1:0];
      if (sys_addr[19:0] == 20'h08) set_dec_log2  <= sys_wdata[3:0];
      if (sys_addr[19:0] == 20'h0C) set_src       <= sys_wdata[0];
      if (sys_addr[19:0] == 20'h10) set_tap_sel   <= sys_wdata[1:0];
      if (sys_addr[19:0] == 20'h14) set_tap_shift <= sys_wdata[4:0];
      if (sys_addr[19:0] == 20'h28) set_mem_start <= sys_wdata[31:0];
      if (sys_addr[19:0] == 20'h2C) set_mem_stop  <= sys_wdata[31:0];
      if (sys_addr[19:0] == 20'h40) coef_addr     <= sys_wdata[8:0];
      if (sys_addr[19:0] == 20'h44) begin
        coef_wdata <= sys_wdata[17:0];
        coef_we    <= 1'b1;    // writing the value is what stores it
      end
    end
  end
end

//=================================================================================
//  SECTION 12 - System bus, read side
//=================================================================================
wire sys_en = sys_wen | sys_ren;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    sys_err   <= 1'b0;
    sys_ack   <= 1'b0;
    sys_rdata <= 32'h0;
  end else begin
    sys_err <= 1'b0;
    sys_ack <= sys_en;
    case (sys_addr[19:0])
      20'h00 : sys_rdata <= {23'h0, set_axi_sel, 1'b0, set_fir_byp, set_wrap, set_arm,
                             set_tap_en, set_test, 1'b0, set_ena};
      20'h04 : sys_rdata <= set_finc;
      20'h08 : sys_rdata <= {28'h0, set_dec_log2};
      20'h0C : sys_rdata <= {31'h0, set_src};
      20'h10 : sys_rdata <= {30'h0, set_tap_sel};
      20'h14 : sys_rdata <= {27'h0, set_tap_shift};
      20'h18 : sys_rdata <= peek_i;
      20'h1C : sys_rdata <= peek_q;
      20'h20 : sys_rdata <= sample_cnt;
      20'h24 : sys_rdata <= {29'h0, set_tap_en, set_test, set_ena};
      20'h28 : sys_rdata <= set_mem_start;
      20'h2C : sys_rdata <= set_mem_stop;
      20'h30 : sys_rdata <= dma_cur_addr;
      20'h34 : sys_rdata <= dma_count;
      // 0x38 STATUS2: everything that can go wrong, in one read.
      //   [0] memory overflow  - samples were LOST. The record still looks
      //                          continuous but time has jumped, so every
      //                          frequency derived from it is wrong.
      //   [1] filter overrun   - an input arrived while the correction filter
      //                          was still working: decimation too small.
      //   [2] filter bypassed  - correction is not being applied, either
      //                          because software asked or because R < 256.
      20'h38 : sys_rdata <= {28'h0, dma_werr, fir_bypass,
                             (fir_ovr_i | fir_ovr_q), dma_overflow};
      20'h40 : sys_rdata <= {23'h0, coef_addr};
      // 0x44 reads back the coefficient CURRENTLY IN THE CHIP at COEF_ADDR,
      // sign-extended to 32 bits. This is how software verifies that what it
      // meant to load is what the hardware actually holds - which is not the
      // same thing, and is worth being able to check.
      20'h44 : sys_rdata <= {{14{coef_rdata[17]}}, coef_rdata};
      // 0x48 is the BUILD FINGERPRINT: a hash of the Verilog this bitstream was
      // synthesised from. It answers "is the chip running the source I am
      // looking at?", which is not a question the file dates can answer - a
      // bitstream can be freshly written and still contain week-old logic.
      // Zero means the bitstream was not produced by project.ps1 build.
      20'h48 : sys_rdata <= GEN_BUILD_ID;
      default: sys_rdata <= 32'h0;
    endcase
  end
end

endmodule
