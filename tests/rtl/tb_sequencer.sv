`timescale 1ns/1ps
module tb;
  reg clk=0, rstn=0, trig=0, wen=0, ren=0;
  reg [31:0] addr=0, wdata=0;
  wire [15:0] ci, cq;
  wire sel, burst, acq_arm;
  wire [31:0] rdata;
  wire err, ack;
  integer n, hold;
  reg [31:0] got;

  red_pitaya_sequencer dut(
    .clk_i(clk), .rstn_i(rstn), .ci_o(ci), .cq_o(cq), .sel_o(sel),
    .burst_o(burst), .acq_arm_o(acq_arm), .trig_i(trig),
    .sys_addr(addr), .sys_wdata(wdata), .sys_wen(wen), .sys_ren(ren),
    .sys_rdata(rdata), .sys_err(err), .sys_ack(ack));

  task tick; begin #4 clk=1; #1; #3 clk=0; #1; end endtask
  task wr(input [31:0] a, input [31:0] d); begin
    addr=a; wdata=d; wen=1; tick;
    if (ack) $fatal(1,"early write ack at %h",a);
    tick; if (!ack) $fatal(1,"missing write ack at %h",a);
    wen=0; tick; if (ack) $fatal(1,"write ack wider than one clock");
  end endtask
  task rd(input [31:0] a, output [31:0] d); begin
    addr=a; ren=1; tick;
    if (ack) $fatal(1,"early read ack at %h",a);
    tick; if (!ack) $fatal(1,"missing read ack at %h",a); d=rdata;
    ren=0; tick; if (ack) $fatal(1,"read ack wider than one clock");
  end endtask

  initial begin
    repeat(4) tick; rstn=1; repeat(2) tick;

    // Captured request must ignore live-bus changes before execution.
    addr=32'h18; wdata=32'h12345678; wen=1; tick;
    if (ack) $fatal(1,"capture acknowledged too early");
    addr=32'h28; wdata=32'hdeadbeef; tick;
    if (!ack) $fatal(1,"captured write not acknowledged");
    wen=0; tick;
    rd(32'h18,got); if (got!==32'h12345678) $fatal(1,"captured data wrong");
    rd(32'h28,got); if (got!==0) $fatal(1,"live address was wrongly used");

    // Every word of every set.
    for(n=0;n<8;n=n+1) begin
      wr(32'h10+16*n,    32'h1000+n);
      wr(32'h14+16*n,    32'h2000+n);
      wr(32'h18+16*n,    32'h10203040+n);
      wr(32'h1c+16*n,    n);
    end
    for(n=0;n<8;n=n+1) begin
      rd(32'h10+16*n,got); if(got!==(32'h1000+n)) $fatal(1,"CI set %0d",n);
      rd(32'h14+16*n,got); if(got!==(32'h2000+n)) $fatal(1,"CQ set %0d",n);
      rd(32'h18+16*n,got); if(got!==(32'h10203040+n)) $fatal(1,"DUR set %0d",n);
      rd(32'h1c+16*n,got); if(got!==n) $fatal(1,"FLAG set %0d",n);
    end
    rd(32'h0c,got); if(got!==32'h5e900001) $fatal(1,"version");
    wr(32'h08,3); rd(32'h08,got); if(got!==3) $fatal(1,"trigger config");

    // Real-time state machine: set 0 duration 3, then last set 1.
    wr(32'h10,16'h1111); wr(32'h14,16'h2222); wr(32'h18,3); wr(32'h1c,0);
    wr(32'h20,16'h3333); wr(32'h24,16'h4444); wr(32'h28,2); wr(32'h2c,4);
    wr(32'h00,5);
    if(!sel || ci!==16'h1111 || cq!==16'h2222) $fatal(1,"set 0 entry");
    for(hold=0;hold<3;hold=hold+1) begin tick; if(ci!==16'h1111) $fatal(1,"set 0 short"); end
    tick; if(ci!==16'h3333 || cq!==16'h4444) $fatal(1,"set 1 entry");
    repeat(3) tick;
    rd(32'h04,got); if(!got[4] || got[2:0]!==1) $fatal(1,"final status %h",got);

    $display("PASS: sequencer registered bus and real-time schedule");
    $finish;
  end
endmodule
