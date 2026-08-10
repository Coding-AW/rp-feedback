// ===========================================================================
//  tb_dac_sum.sv - the top level's DAC summation leg, lifted VERBATIM.
//
//  WHY. Until 2026-08-07 red_pitaya_phaseshift drove `dat_b_o` to a constant
//  zero, so `pid_dat[1]` had never carried a negative number, and the CH B
//  half of this arithmetic had never actually been exercised. The OUT2 monitor
//  changes that on the first sample.
//
//  The specific worry is signedness. `SBA_T` is `logic signed [13:0]`, but
//  `pid_dat` is a PACKED ARRAY of it, and in SystemVerilog a part-select of a
//  packed array is UNSIGNED regardless of the element type. If that applies
//  here, `asg_dat[1] + pid_dat[1]` would zero-extend a negative sample and the
//  saturation below would slam it to the opposite rail - a monitor that turns
//  every negative half-cycle into a positive clip, which on a spectrum
//  analyser looks like a signal, not like a fault.
//
//  Reasoning about it from the language reference is not good enough: this
//  project has already lost a day to "a concatenation in Verilog is unsigned".
//  So the lines are copied out of red_pitaya_top.sv character for character
//  and run.
//
//  The A channel is included alongside, unchanged, as the control: it is the
//  working, characterised feedback output. If A and B behave identically then
//  whatever the language does here, the monitor inherits a path that is known
//  good on hardware.
// ===========================================================================
`timescale 1ns / 1ps

module tb_dac_sum (
  input  logic [14-1:0] pid_b_i,     // what red_pitaya_phaseshift now drives
  input  logic [14-1:0] asg_b_i,     // generator channel 2
  input  logic [14-1:0] pid_a_i,     // the control: the working feedback output
  input  logic [14-1:0] asg_a_i,
  output logic [14-1:0] dac_dat_a_o,
  output logic [14-1:0] dac_dat_b_o,
  output logic [14-1:0] dac_a_o,
  output logic [14-1:0] dac_b_o
);

// ===========================================================================
//  TWO DELIBERATE REWRITES, AND WHY. READ THIS BEFORE TRUSTING THE RESULT.
//
//  (1) The real file declares the operands through a type parameter:
//
//          localparam type SBA_T = logic signed [14-1:0];
//          SBA_T [2-1:0] pid_dat;
//
//      Yosys cannot parse `localparam type` at all. Vivado accepts it.
//
//  (2) Worse, and the actual reason this file looks the way it does: Yosys
//      0.68 LOSES THE SIGNEDNESS of an element select on a packed array of a
//      signed type. Measured, on this machine, with minimal.sv:
//
//          logic signed [1:0][13:0] arr;   0 + arr[1]  with arr[1] = -1
//              Yosys 0.68 -> 16383      (zero-extended: wrong)
//              slang      ->    -1      (sign-extended: correct)
//          logic signed [13:0] sca;        0 + sca     with sca = -1
//              Yosys 0.68 ->    -1
//              slang      ->    -1
//
//      So an earlier version of this testbench, written verbatim, reported
//      that a monitor sample of -1 came out of the DAC as +8191 - a
//      catastrophic-looking result that was entirely an artefact of the
//      simulator. It is recorded here because it is exactly the sort of
//      false alarm that gets a good design "fixed" into a bad one.
//
//  WHAT SETTLES IT. Two independent things, neither of them Yosys:
//
//    * slang, which implements the full language and agrees with Vivado,
//      canonicalises both spellings to `logic signed[1:0][13:0]`, reports the
//      element type as `logic signed[13:0]`, and constant-folds `arr[1]` with
//      a bit pattern of all ones to -15'sd1. The element select is SIGNED.
//
//    * channel A. `dac_a_sum = asg_dat[0] + pid_dat[0]` is the same construct
//      carrying the phase shifter's output, and that loop has been closed and
//      characterised on real hardware. If Vivado behaved the way Yosys does,
//      every negative half-cycle would have folded to +8191 and nothing in
//      this project would ever have worked.
//
//  So the operands below are plain signed scalars - the semantics Vivado
//  gives the real declaration - and what this file still tests honestly is
//  the SATURATION ARITHMETIC that the monitor will now exercise on CH B for
//  the first time. The signedness question is answered above, not here.
// ===========================================================================
logic        [14-1:0] dac_dat_a, dac_dat_b;
logic        [14-1:0] dac_a    , dac_b    ;
logic signed [15-1:0] dac_a_sum, dac_b_sum;

logic signed [14-1:0] asg_a, asg_b;
logic signed [14-1:0] pid_a, pid_b;

assign asg_a = asg_a_i;
assign asg_b = asg_b_i;
assign pid_a = pid_a_i;
assign pid_b = pid_b_i;

// ---- arithmetic, verbatim from red_pitaya_top.sv lines 380-391 ----
// Sumation of ASG and PID signal perform saturation before sending to DAC
assign dac_a_sum = asg_a + pid_a;
assign dac_b_sum = asg_b + pid_b;

// saturation
assign dac_a = (^dac_a_sum[15-1:15-2]) ? {dac_a_sum[15-1], {13{~dac_a_sum[15-1]}}} : dac_a_sum[14-1:0];
assign dac_b = (^dac_b_sum[15-1:15-2]) ? {dac_b_sum[15-1], {13{~dac_b_sum[15-1]}}} : dac_b_sum[14-1:0];

// output registers + signed to unsigned (also to negative slope)
// (registered in the real file; combinational here so one evaluation suffices)
assign dac_dat_a = {dac_a[14-1], ~dac_a[14-2:0]};
assign dac_dat_b = {dac_b[14-1], ~dac_b[14-2:0]};

assign dac_dat_a_o = dac_dat_a;
assign dac_dat_b_o = dac_dat_b;
assign dac_a_o     = dac_a;
assign dac_b_o     = dac_b;

endmodule
