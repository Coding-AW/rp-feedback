/**
 * @brief Packing, buffering and streaming to memory (block 4) for the
 *        acquisition system.
 *
 * Project-specific acquisition module.
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * Part of the acquisition system of Herkenhoff et al., Rev. Sci. Instrum. 92,
 * 103201 (2021).  Fig. 6a, the blocks labelled "FIFO" and "DMA" and the arrow
 * into "Main memory".
 *
 * ===========================================================================
 *  WHAT THIS BLOCK IS FOR
 * ===========================================================================
 *  Everything up to here lives in the programmable-logic half of the chip. This
 *  block carries the finished numbers across into the main memory, where the
 *  Linux half - and therefore Python - can read them.
 *
 *  Three jobs, in order:
 *
 *  1. PACK. The I and Q values are 32 bits each. They are glued into one 64-bit
 *     word, because 64 bits is the natural width of the memory interface: one
 *     transfer carries a complete sample rather than half of one. This also
 *     makes it impossible for I and Q to become separated in transit.
 *
 *  2. BUFFER. The chain produces samples at a perfectly steady rate. Memory
 *     accepts them in irregular bursts, because the processor and its own
 *     memory traffic compete for the same path. A queue absorbs the mismatch.
 *     (Called a FIFO - first in, first out - because samples come out in the
 *     order they went in.)
 *
 *  3. TRANSFER. A dedicated engine writes the queue into memory without the
 *     processor fetching each number itself.
 *
 *  Jobs 2 and 3 are done by `axi_wr_fifo`, which is Red Pitaya's own module and
 *  is already proven on this board - it is what the stock oscilloscope uses for
 *  its long captures. Reusing it rather than writing a new memory-transfer
 *  engine removes the single largest source of risk in this block.
 *
 * ===========================================================================
 *  WORD LAYOUT  -  and why it is this way round
 * ===========================================================================
 *      bits 63..32 : Q
 *      bits 31.. 0 : I
 *
 *  The processor is little-endian, so a 64-bit word read as two 32-bit numbers
 *  comes out as [I, Q] in that order. In Python:
 *
 *      raw = np.frombuffer(buf, dtype='<i4')     # signed 32-bit, little-endian
 *      I   = raw[0::2]
 *      Q   = raw[1::2]
 *
 *  Getting this the wrong way round swaps I and Q, which rotates every measured
 *  phase by 90 degrees and mirrors the spectrum - plausible-looking and wrong.
 *  The test-pattern mode in red_pitaya_acq exists partly to catch exactly that:
 *  it sets I to a counter and Q to its complement, so I + Q must equal
 *  0xFFFFFFFF for every sample. If the halves are swapped that still holds, but
 *  the counter runs in the wrong field and is immediately obvious.
 *
 * ===========================================================================
 *  MEMORY REGION  -  READ THIS BEFORE USING
 * ===========================================================================
 *  This block writes directly into physical memory at whatever address software
 *  gives it. Nothing stops it writing over Linux. The region MUST be one that
 *  Linux has been told not to use, which on the Red Pitaya means a reserved
 *  block near the top of memory.
 *
 *  The stock oscilloscope uses the same mechanism, so a region that is safe for
 *  it is safe here. Start and stop addresses are set by software; see the
 *  register map in red_pitaya_acq.v.
 *
 *  `set_wrap_i` chooses what happens at the end of the region:
 *      1 = wrap round and overwrite the oldest data (continuous recording)
 *      0 = stop (single capture of a fixed length)
 *
 * ===========================================================================
 *  OVERFLOW  -  why it is reported rather than ignored
 * ===========================================================================
 *  If memory cannot keep up, the queue fills and samples are lost. Lost samples
 *  are far more damaging than they sound: the record still looks like a
 *  continuous measurement, but time has silently jumped, so every frequency
 *  derived from it is wrong.
 *
 *  `stat_overflow_o` latches if that ever happens, and stays latched until the
 *  next clear, so a brief overflow cannot be missed between two reads.
 *
 *  At the highest data rate this design produces - decimation 256, the smallest
 *  that allows the correction filter - the load is
 *
 *      125 MHz / 256 = 488 kSample/s  x  8 bytes  =  3.9 MB/s
 *
 *  against a memory interface good for hundreds of megabytes per second. There
 *  is a very large margin, but the flag costs almost nothing and turns a silent
 *  corruption into a visible one.
 */

`timescale 1ns / 1ps

module red_pitaya_acq_dma #(
  parameter integer DW = 32,   // width of each of I and Q
  parameter integer AW = 32    // memory address width
)(
  // ---- clock and reset ----
  input                   clk_i          ,  //!< 125 MHz processing clock
  input                   rstn_i         ,  //!< active-LOW reset

  // ---- data in, from the correction filter (or the decimator if bypassed) ----
  input      [ DW-1: 0]   dat_i_i        ,  //!< I
  input      [ DW-1: 0]   dat_q_i        ,  //!< Q
  input                   stb_i          ,  //!< 1 clock high per sample

  // ---- control ----
  input                   arm_i          ,  //!< 1 = write samples to memory
  input      [ AW-1: 0]   set_start_i    ,  //!< first address of the region
  input      [ AW-1: 0]   set_stop_i     ,  //!< last address of the region
  input                   set_wrap_i     ,  //!< 1 = wrap at the end, 0 = stop
  input                   clr_i          ,  //!< 1 clock high: flush and restart

  // ---- status ----
  output reg              stat_overflow_o,  //!< sticky: samples were lost
  output reg              stat_werr_o    ,  //!< sticky: memory REFUSED a write
  output     [ AW-1: 0]   stat_cur_addr_o,  //!< address currently being written
  output reg [ 32-1: 0]   stat_count_o   ,  //!< samples handed to the queue

  // ---- connection to the memory-write master in red_pitaya_ps ----
  output                  axi_clk_o      ,
  output                  axi_rstn_o     ,
  output     [ AW-1: 0]   axi_waddr_o    ,
  output     [ 64-1: 0]   axi_wdata_o    ,
  output     [  8-1: 0]   axi_wsel_o     ,
  output                  axi_wvalid_o   ,
  output     [  4-1: 0]   axi_wlen_o     ,
  output                  axi_wfixed_o   ,
  input                   axi_werr_i     ,
  input                   axi_wrdy_i
);

//---------------------------------------------------------------------------------
//  The memory-write engine runs on the same clock as everything else here, so
//  there is no clock-domain crossing to get wrong.
//---------------------------------------------------------------------------------
assign axi_clk_o  = clk_i;
assign axi_rstn_o = rstn_i;

//---------------------------------------------------------------------------------
//  1. PACK  -  glue I and Q into one 64-bit word
//
//  Registered rather than wired straight through, so the wide word is driven
//  from a flip-flop close to the queue instead of dragging 64 bits of
//  combinational logic across the chip.
//---------------------------------------------------------------------------------
reg [ 64-1: 0] wr_data;
reg            wr_valid;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    wr_data  <= 64'h0;
    wr_valid <= 1'b0;
  end else begin
    wr_data  <= {dat_q_i, dat_i_i};      // Q in the upper half, I in the lower
    wr_valid <= stb_i & arm_i;           // only write when software has armed it
  end
end

//---------------------------------------------------------------------------------
//  Sample counter - how many samples have been handed to the queue since the
//  last clear. Software uses it to know how much of the region is filled, and
//  to check against the number of samples it expected.
//---------------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (rstn_i == 1'b0)  stat_count_o <= 32'h0;
  else if (clr_i)      stat_count_o <= 32'h0;
  else if (wr_valid)   stat_count_o <= stat_count_o + 1'b1;
end

//---------------------------------------------------------------------------------
//  Overflow latch
//
//  The queue reports overflow as a level. Latching it means a brief overflow
//  between two software reads cannot be missed - which matters, because a
//  handful of lost samples is enough to corrupt every frequency measured from
//  the record while leaving it looking perfectly normal.
//---------------------------------------------------------------------------------
wire fifo_overflow;

always @(posedge clk_i) begin
  if (rstn_i == 1'b0)      stat_overflow_o <= 1'b0;
  else if (clr_i)          stat_overflow_o <= 1'b0;
  else if (fifo_overflow)  stat_overflow_o <= 1'b1;
end

//---------------------------------------------------------------------------------
//  Write-error latch
//
//  `axi_werr_i` pulses whenever memory answers a write with an error rather than
//  an acknowledgement. It has been wired into this module since it was written
//  and, until now, thrown away - which meant that "the writes were accepted" and
//  "the writes succeeded" could not be told apart from software.
//
//  That distinction is not academic. On 2026-07-29 the address counter advanced
//  by exactly eight bytes per sample, the overflow flag stayed clear, and the
//  memory read back unchanged. Every signal software could see said the transfer
//  had worked. This is the signal that was missing.
//
//  Sticky, and cleared by the same clr_i as everything else, so a brief error
//  between two reads cannot be missed.
//---------------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (rstn_i == 1'b0)   stat_werr_o <= 1'b0;
  else if (clr_i)       stat_werr_o <= 1'b0;
  else if (axi_werr_i)  stat_werr_o <= 1'b1;
end

//---------------------------------------------------------------------------------
//  2 and 3. BUFFER and TRANSFER
//
//  Red Pitaya's own module, unmodified. FW = 8 gives a 256-entry queue; the
//  paper specifies 2048 entries, but that figure is for a design streaming at
//  the full sample rate. Here the fastest usable setting produces 488 thousand
//  samples a second against a memory interface hundreds of times quicker, so
//  the queue only ever has to cover brief moments when memory is busy
//  elsewhere. The overflow flag above proves whether that judgement holds.
//
//  ctrl_trig_size_i = 4'hF asks the engine to gather full-length bursts before
//  going to memory, which is far more efficient than writing single words.
//---------------------------------------------------------------------------------
axi_wr_fifo #(
  .DW  (64),      // data width - one packed I/Q sample
  .AW  (AW),      // address width
  .FW  (8 )       // queue depth = 2^8 = 256 entries
) i_wr_fifo (
  // to the memory-write master
  .axi_clk_i          ( clk_i           ),
  .axi_rstn_i         ( rstn_i          ),
  .axi_waddr_o        ( axi_waddr_o     ),
  .axi_wdata_o        ( axi_wdata_o     ),
  .axi_wsel_o         ( axi_wsel_o      ),
  .axi_wvalid_o       ( axi_wvalid_o    ),
  .axi_wlen_o         ( axi_wlen_o      ),
  .axi_wfixed_o       ( axi_wfixed_o    ),
  .axi_werr_i         ( axi_werr_i      ),
  .axi_wrdy_i         ( axi_wrdy_i      ),
  // data and configuration
  .wr_data_i          ( wr_data         ),
  .wr_val_i           ( wr_valid        ),
  .ctrl_start_addr_i  ( set_start_i     ),
  .ctrl_stop_addr_i   ( set_stop_i      ),
  .ctrl_trig_size_i   ( 4'hF            ),   // gather full bursts
  .ctrl_wrap_i        ( set_wrap_i      ),
  .ctrl_clr_i         ( clr_i           ),
  .stat_overflow_o    ( fifo_overflow   ),
  .stat_cur_addr_o    ( stat_cur_addr_o ),
  .stat_write_data_o  (                 )    // not needed
);

endmodule
