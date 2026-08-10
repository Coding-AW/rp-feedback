`timescale 1ns/1ps

// Small lift of the top-level OUT2 and digital-loopback leg. The arithmetic is
// kept identical to red_pitaya_top.sv so this test can exercise it without the
// processing-system IP and physical I/O primitives required by the full top.
module out2_loopback_leg (
  input  logic               clk,
  input  logic               rstn,
  input  logic               digital_loop,
  input  logic signed [13:0] real_adc_b,
  input  logic signed [13:0] asg_b,
  input  logic signed [13:0] monitor_b,
  output logic signed [13:0] adc_b,
  output logic signed [13:0] dac_b,
  output logic        [13:0] connector_word
);
  logic signed [14:0] dac_b_sum;
  logic signed [13:0] dac_loop_b;

  assign dac_b_sum = asg_b + monitor_b;
  assign dac_b = (^dac_b_sum[14:13])
               ? {dac_b_sum[14], {13{~dac_b_sum[14]}}}
               : dac_b_sum[13:0];

  always_ff @(posedge clk)
    if (!rstn) dac_loop_b <= 14'sd0;
    else       dac_loop_b <= dac_b;

  assign adc_b = digital_loop ? dac_loop_b : real_adc_b;
  assign connector_word = {dac_b[13], ~dac_b[12:0]};
endmodule

module tb_timing_fixes;
  logic clk=0, rstn=0, digital_loop=0;
  logic signed [13:0] real_adc_b=0, asg_b=0, monitor_b=0;
  wire  signed [13:0] loop_adc_b, top_dac_b;
  wire         [13:0] connector_word;

  out2_loopback_leg leg(
    .clk(clk), .rstn(rstn), .digital_loop(digital_loop),
    .real_adc_b(real_adc_b), .asg_b(asg_b), .monitor_b(monitor_b),
    .adc_b(loop_adc_b), .dac_b(top_dac_b), .connector_word(connector_word));

  logic signed [13:0] ps_in=0;
  logic [31:0] ps_addr=0, ps_wdata=0;
  logic ps_wen=0, ps_ren=0;
  wire signed [13:0] ps_a, ps_b;
  wire [31:0] ps_rdata;
  wire ps_err, ps_ack;

  red_pitaya_phaseshift ps(
    .clk_i(clk), .rstn_i(rstn), .dat_a_i(ps_in), .dat_b_i(14'd0),
    .dat_a_o(ps_a), .dat_b_o(ps_b), .ci_ext_i(16'd0), .cq_ext_i(16'd0),
    .ext_sel_i(1'b0), .sys_addr(ps_addr), .sys_wdata(ps_wdata),
    .sys_wen(ps_wen), .sys_ren(ps_ren), .sys_rdata(ps_rdata),
    .sys_err(ps_err), .sys_ack(ps_ack));

  integer n, idx_f, idx_c;
  logic signed [13:0] shadow [0:1023];
  logic signed [13:0] expect_f, expect_c, sample;
  integer shadow_wp=0;

  task tick; begin #4 clk=1; #1; #3 clk=0; #1; end endtask
  task ps_wr(input [31:0] a, input [31:0] d); begin
    ps_addr=a; ps_wdata=d; ps_wen=1; tick; ps_wen=0; tick;
  end endtask

  function automatic signed [13:0] sat14(input integer v);
    if (v > 8191)       sat14 = 14'sd8191;
    else if (v < -8192) sat14 = -14'sd8192;
    else                sat14 = v;
  endfunction

  initial begin
    for(n=0;n<1024;n=n+1) shadow[n]=0;
    repeat(4) tick; rstn=1; repeat(3) tick;

    // Normal acquisition is completely independent of DAC/monitor activity.
    digital_loop=0; real_adc_b=-14'sd1234; asg_b=14'sd7000; monitor_b=14'sd6000;
    #1; if(loop_adc_b!==-14'sd1234) $fatal(1,"physical ADC path changed");
    tick; if(loop_adc_b!==-14'sd1234) $fatal(1,"physical ADC acquired latency");

    // Generator-only, monitor-only and combined OUT2 all use the same saturator.
    asg_b=14'sd1200; monitor_b=0; #1;
    if(top_dac_b!==14'sd1200) $fatal(1,"generator-only OUT2");
    asg_b=0; monitor_b=-14'sd2300; #1;
    if(top_dac_b!==-14'sd2300) $fatal(1,"monitor-only OUT2");
    asg_b=14'sd3000; monitor_b=-14'sd800; #1;
    if(top_dac_b!==14'sd2200) $fatal(1,"combined OUT2");
    asg_b=14'sd7000; monitor_b=14'sd6000; #1;
    if(top_dac_b!==14'sd8191) $fatal(1,"positive OUT2 saturation");
    asg_b=-14'sd7000; monitor_b=-14'sd6000; #1;
    if(top_dac_b!==-14'sd8192) $fatal(1,"negative OUT2 saturation");
    if(connector_word!=={top_dac_b[13],~top_dac_b[12:0]})
      $fatal(1,"OUT2 converter inversion");

    // Internal loopback is exactly the previous DAC sample; no combinational
    // OUT2-to-mixer route remains. Physical mode above retained zero latency.
    digital_loop=1; asg_b=14'sd111; monitor_b=14'sd222; tick;
    if(loop_adc_b!==14'sd333) $fatal(1,"registered loopback first sample");
    asg_b=-14'sd444; monitor_b=14'sd100; #1;
    if(loop_adc_b!==14'sd333) $fatal(1,"loopback changed before clock");
    tick; if(loop_adc_b!==-14'sd344) $fatal(1,"registered loopback second sample");

    // Monitor defaults off, then carries the selected input with the documented
    // pipeline. This is the source ultimately delivered to the OUT2 leg above.
    if(ps_b!==0) $fatal(1,"OUT2 monitor not off after reset");
    ps_wr(32'h18,32'h1);                 // input source, shift 0
    ps_in=14'sd321; repeat(4) tick;
    if(ps_b!==14'sd321) $fatal(1,"OUT2 monitor source failed");

    // Configure a fixed delay and prove both block-memory copies receive the
    // same sample while their independent registered reads return floor/ceil.
    ps_wr(32'h08,32'd5);
    repeat(3) tick;                       // dly_eff settles
    shadow_wp = ps.wp;
    for(n=0;n<1100;n=n+1) begin
      sample = $signed((n*37) & 14'h3fff);
      ps_in = sample;
      idx_f = (shadow_wp - 5) & 1023;
      idx_c = (shadow_wp - 6) & 1023;
      expect_f = shadow[idx_f];
      expect_c = shadow[idx_c];
      tick;
      if(n>10 && ps.q_flr!==expect_f) $fatal(1,"floor read mismatch at %0d",n);
      if(n>10 && ps.q_cel!==expect_c) $fatal(1,"ceil read mismatch at %0d",n);
      shadow[shadow_wp] = sample;
      shadow_wp = (shadow_wp + 1) & 1023;
    end
    for(n=0;n<1024;n=n+1)
      if(ps.dly_mem_flr[n]!==ps.dly_mem_cel[n])
        $fatal(1,"delay memory copies differ at %0d",n);

    $display("PASS: registered loopback, OUT2 path and duplicated delay memory");
    $finish;
  end
endmodule
