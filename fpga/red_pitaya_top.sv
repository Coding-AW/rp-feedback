////////////////////////////////////////////////////////////////////////////////
// Red Pitaya TOP module. It connects external pins and PS part with
// other application modules.
// Authors: Matej Oblak, Iztok Jeras
// (c) Red Pitaya  http://www.redpitaya.com
////////////////////////////////////////////////////////////////////////////////

/**
 * GENERAL DESCRIPTION:
 *
 * Top module connects PS part with rest of Red Pitaya applications.  
 *
 *                   /-------\      
 *   PS DDR <------> |  PS   |      AXI <-> custom bus
 *   PS MIO <------> |   /   | <------------+
 *   PS CLK -------> |  ARM  |              |
 *                   \-------/              |
 *                                          |
 *                            /-------\     |
 *                         -> | SCOPE | <---+
 *                         |  \-------/     |
 *                         |                |
 *            /--------\   |   /-----\      |
 *   ADC ---> |        | --+-> |     |      |
 *            | ANALOG |       | PID | <----+
 *   DAC <--- |        | <---- |     |      |
 *            \--------/   ^   \-----/      |
 *                         |                |
 *                         |  /-------\     |
 *                         -- |  ASG  | <---+ 
 *                            \-------/     |
 *                                          |
 *             /--------\                   |
 *    RX ----> |        |                   |
 *   SATA      | DAISY  | <-----------------+
 *    TX <---- |        | 
 *             \--------/ 
 *               |    |
 *               |    |
 *               (FREE)
 *
 * Inside analog module, ADC data is translated from unsigned neg-slope into
 * two's complement. Similar is done on DAC data.
 *
 * Scope module stores data from ADC into RAM, arbitrary signal generator (ASG)
 * sends data from RAM to DAC. MIMO PID uses ADC ADC as input and DAC as its output.
 *
 * Daisy chain connects with other boards with fast serial link. Data which is
 * send and received is at the moment undefined. This is left for the user.
 */

module red_pitaya_top #(
  // identification
  bit [0:5*32-1] GITH = '0,
  // module numbers
  int unsigned MNA = 2,  // number of acquisition modules
  int unsigned MNG = 2   // number of generator   modules
)( // PS connections
  inout  logic [54-1:0] FIXED_IO_mio     ,
  inout  logic          FIXED_IO_ps_clk  ,
  inout  logic          FIXED_IO_ps_porb ,
  inout  logic          FIXED_IO_ps_srstb,
  inout  logic          FIXED_IO_ddr_vrn ,
  inout  logic          FIXED_IO_ddr_vrp ,
  // DDR
  inout  logic [15-1:0] DDR_addr   ,
  inout  logic [ 3-1:0] DDR_ba     ,
  inout  logic          DDR_cas_n  ,
  inout  logic          DDR_ck_n   ,
  inout  logic          DDR_ck_p   ,
  inout  logic          DDR_cke    ,
  inout  logic          DDR_cs_n   ,
  inout  logic [ 4-1:0] DDR_dm     ,
  inout  logic [32-1:0] DDR_dq     ,
  inout  logic [ 4-1:0] DDR_dqs_n  ,
  inout  logic [ 4-1:0] DDR_dqs_p  ,
  inout  logic          DDR_odt    ,
  inout  logic          DDR_ras_n  ,
  inout  logic          DDR_reset_n,
  inout  logic          DDR_we_n   ,

  // Red Pitaya periphery

  // ADC
  input  logic [MNA-1:0] [16-1:0] adc_dat_i,  // ADC data
  input  logic           [ 2-1:0] adc_clk_i,  // ADC clock {p,n}
  output logic           [ 2-1:0] adc_clk_o,  // optional ADC clock source (unused) [0] = p; [1] = n
  output logic                    adc_cdcs_o, // ADC clock duty cycle stabilizer
  // DAC
  output logic [14-1:0] dac_dat_o  ,  // DAC combined data
  output logic          dac_wrt_o  ,  // DAC write
  output logic          dac_sel_o  ,  // DAC channel select
  output logic          dac_clk_o  ,  // DAC clock
  output logic          dac_rst_o  ,  // DAC reset
  // PWM DAC
  output logic [ 4-1:0] dac_pwm_o  ,  // 1-bit PWM DAC
  // XADC
  input  logic [ 5-1:0] vinp_i     ,  // voltages p
  input  logic [ 5-1:0] vinn_i     ,  // voltages n
  // Expansion connector
  inout  logic [ 8-1:0] exp_p_io   ,
  inout  logic [ 8-1:0] exp_n_io   ,
  // SATA connector
  output logic [ 2-1:0] daisy_p_o  ,  // line 1 is clock capable
  output logic [ 2-1:0] daisy_n_o  ,
  input  logic [ 2-1:0] daisy_p_i  ,  // line 1 is clock capable
  input  logic [ 2-1:0] daisy_n_i  ,
  // LED
  output  logic [ 8-1:0] led_o          // EDIT: TO CONFIGURE FLICKERING LED
);

////////////////////////////////////////////////////////////////////////////////
// local signals
////////////////////////////////////////////////////////////////////////////////

// GPIO parameter
localparam int unsigned GDW = 8+8;

logic [4-1:0] fclk ; //[0]-125MHz, [1]-250MHz, [2]-50MHz, [3]-200MHz
logic [4-1:0] frstn;

// AXI masters
logic            axi1_clk    , axi0_clk    ;
logic            axi1_rstn   , axi0_rstn   ;
logic [ 32-1: 0] axi1_waddr  , axi0_waddr  ;
logic [ 64-1: 0] axi1_wdata  , axi0_wdata  ;
logic [  8-1: 0] axi1_wsel   , axi0_wsel   ;
logic            axi1_wvalid , axi0_wvalid ;
logic [  4-1: 0] axi1_wlen   , axi0_wlen   ;
logic            axi1_wfixed , axi0_wfixed ;
logic            axi1_werr   , axi0_werr   ;
logic            axi1_wrdy   , axi0_wrdy   ;

// PLL signals
logic                 adc_clk_in;
logic                 pll_adc_clk;
logic                 pll_dac_clk_1x;
logic                 pll_dac_clk_2x;
logic                 pll_dac_clk_2p;
logic                 pll_ser_clk;
logic                 pll_pwm_clk;
logic                 pll_locked;
// (ser_clk, pwm_clk and pwm_rstn declarations removed - the daisy chain and PWM
//  outputs that used them are gone. The PLL still generates pll_ser_clk and
//  pll_pwm_clk; those outputs are simply left unconnected.)

// ADC clock/reset
logic                 adc_clk;
logic                 adc_rstn;

// stream bus type
localparam type SBA_T = logic signed [14-1:0];  // acquire
localparam type SBG_T = logic signed [14-1:0];  // generate

SBA_T [MNA-1:0]          adc_dat;

// DAC signals
logic                    dac_clk_1x;
logic                    dac_clk_2x;
logic                    dac_clk_2p;
logic                    dac_rst;

logic        [14-1:0] dac_dat_a, dac_dat_b;
logic        [14-1:0] dac_a    , dac_b    ;
logic signed [15-1:0] dac_a_sum, dac_b_sum;

// Registered copies used ONLY by the internal diagnostic loopback. The real
// DAC outputs continue to use dac_a/dac_b directly below. Without this clock
// boundary, enabling digital_loop made one path run from the OUT2 monitor,
// through DAC summation and saturation, straight into the acquisition mixer's
// DSP input in a single 8 ns clock. The register adds one deterministic sample
// to the diagnostic loopback only; physical ADC, DAC and feedback paths do not
// pass through it.
SBA_T [2-1:0]            dac_loop;

// ASG
SBG_T [2-1:0]            asg_dat;

// PID
SBA_T [2-1:0]            pid_dat;

// configuration
logic                    digital_loop;

// system bus
sys_bus_if   ps_sys      (.clk (adc_clk), .rstn (adc_rstn));
sys_bus_if   sys [8-1:0] (.clk (adc_clk), .rstn (adc_rstn));

// GPIO interface
gpio_if #(.DW (24)) gpio ();

////////////////////////////////////////////////////////////////////////////////
// PLL (clock and reset)
////////////////////////////////////////////////////////////////////////////////

// diferential clock input
IBUFDS i_clk (.I (adc_clk_i[1]), .IB (adc_clk_i[0]), .O (adc_clk_in));  // differential clock input

red_pitaya_pll pll (
  // inputs
  .clk         (adc_clk_in),  // clock
  .rstn        (frstn[0]  ),  // reset - active low
  // output clocks
  .clk_adc     (pll_adc_clk   ),  // ADC clock
  .clk_dac_1x  (pll_dac_clk_1x),  // DAC clock 125MHz
  .clk_dac_2x  (pll_dac_clk_2x),  // DAC clock 250MHz
  .clk_dac_2p  (pll_dac_clk_2p),  // DAC clock 250MHz -45DGR
  .clk_ser     (pll_ser_clk   ),  // fast serial clock
  .clk_pdm     (pll_pwm_clk   ),  // PWM clock
  // status outputs
  .pll_locked  (pll_locked)
);

BUFG bufg_adc_clk    (.O (adc_clk   ), .I (pll_adc_clk   ));
BUFG bufg_dac_clk_1x (.O (dac_clk_1x), .I (pll_dac_clk_1x));
BUFG bufg_dac_clk_2x (.O (dac_clk_2x), .I (pll_dac_clk_2x));
BUFG bufg_dac_clk_2p (.O (dac_clk_2p), .I (pll_dac_clk_2p));
// EDIT (acquisition system cleanup): two clock buffers REMOVED.
//
//   BUFG bufg_ser_clk (.O (ser_clk), .I (pll_ser_clk));   // fed the daisy chain
//   BUFG bufg_pwm_clk (.O (pwm_clk), .I (pll_pwm_clk));   // fed the PWM outputs
//
// Both drove modules that have now been removed, so they buffered clocks that
// went nowhere. Worth taking out rather than leaving to the optimiser: a BUFG is
// one of a small number of global clock-routing resources on the device, and
// every clock domain that exists adds rows to the timing report that have to be
// read and dismissed.
//
// The PLL still generates both clocks - its outputs are simply left unconnected.
// That is deliberate: changing the PLL's configuration risks disturbing the ADC
// and DAC clocks, which everything depends on, for no benefit.
//
// TO REVERT: restore the two BUFG lines above and the PWM reset below.

// ADC reset (active low)
always @(posedge adc_clk)
adc_rstn <=  frstn[0] &  pll_locked;

// DAC reset (active high)
always @(posedge dac_clk_1x)
dac_rst  <= ~frstn[0] | ~pll_locked;

// PWM reset removed with the PWM clock buffer above - nothing used it.

////////////////////////////////////////////////////////////////////////////////
//  Connections to PS
////////////////////////////////////////////////////////////////////////////////

red_pitaya_ps ps (
  .FIXED_IO_mio       (  FIXED_IO_mio                ),
  .FIXED_IO_ps_clk    (  FIXED_IO_ps_clk             ),
  .FIXED_IO_ps_porb   (  FIXED_IO_ps_porb            ),
  .FIXED_IO_ps_srstb  (  FIXED_IO_ps_srstb           ),
  .FIXED_IO_ddr_vrn   (  FIXED_IO_ddr_vrn            ),
  .FIXED_IO_ddr_vrp   (  FIXED_IO_ddr_vrp            ),
  // DDR
  .DDR_addr      (DDR_addr    ),
  .DDR_ba        (DDR_ba      ),
  .DDR_cas_n     (DDR_cas_n   ),
  .DDR_ck_n      (DDR_ck_n    ),
  .DDR_ck_p      (DDR_ck_p    ),
  .DDR_cke       (DDR_cke     ),
  .DDR_cs_n      (DDR_cs_n    ),
  .DDR_dm        (DDR_dm      ),
  .DDR_dq        (DDR_dq      ),
  .DDR_dqs_n     (DDR_dqs_n   ),
  .DDR_dqs_p     (DDR_dqs_p   ),
  .DDR_odt       (DDR_odt     ),
  .DDR_ras_n     (DDR_ras_n   ),
  .DDR_reset_n   (DDR_reset_n ),
  .DDR_we_n      (DDR_we_n    ),
  // system signals
  .fclk_clk_o    (fclk        ),
  .fclk_rstn_o   (frstn       ),
  // ADC analog inputs
  .vinp_i        (vinp_i      ),
  .vinn_i        (vinn_i      ),
  // GPIO
  .gpio          (gpio),
  // system read/write channel
  .bus           (ps_sys      ),
  // AXI masters
  .axi1_clk_i    (axi1_clk    ),  .axi0_clk_i    (axi0_clk    ),  // global clock
  .axi1_rstn_i   (axi1_rstn   ),  .axi0_rstn_i   (axi0_rstn   ),  // global reset
  .axi1_waddr_i  (axi1_waddr  ),  .axi0_waddr_i  (axi0_waddr  ),  // system write address
  .axi1_wdata_i  (axi1_wdata  ),  .axi0_wdata_i  (axi0_wdata  ),  // system write data
  .axi1_wsel_i   (axi1_wsel   ),  .axi0_wsel_i   (axi0_wsel   ),  // system write byte select
  .axi1_wvalid_i (axi1_wvalid ),  .axi0_wvalid_i (axi0_wvalid ),  // system write data valid
  .axi1_wlen_i   (axi1_wlen   ),  .axi0_wlen_i   (axi0_wlen   ),  // system write burst length
  .axi1_wfixed_i (axi1_wfixed ),  .axi0_wfixed_i (axi0_wfixed ),  // system write burst type (fixed / incremental)
  .axi1_werr_o   (axi1_werr   ),  .axi0_werr_o   (axi0_werr   ),  // system write error
  .axi1_wrdy_o   (axi1_wrdy   ),  .axi0_wrdy_o   (axi0_wrdy   )   // system write ready
);

////////////////////////////////////////////////////////////////////////////////
// system bus decoder & multiplexer (it breaks memory addresses into 8 regions)
////////////////////////////////////////////////////////////////////////////////

sys_bus_interconnect #(
  .SN (8),
  .SW (20)
) sys_bus_interconnect (
  .bus_m (ps_sys),
  .bus_s (sys)
);

// silence unused busses
//
// EDIT (acquisition system): slot sys[6] is now used by red_pitaya_acq at base
// address 0x40600000, so only sys[7] is left stubbed. A stub answers bus reads
// with zero and acknowledges them, which stops an access to an unused address
// from hanging the bus - so every slot must have either a real module or a stub.
// Slots in use:  0 housekeeping, 1 scope, 2 signal generator,
//                3 phase shifter, 6 acquisition system.
// Slot 4 holds the digital resonator (0x40400000) and slot 7 the parameter
// sequencer (0x40700000). Slot 5 (was daisy chain) is unused and must still be
// stubbed - a stub acknowledges bus accesses and returns zero, so
// software touching an unused address gets a clean answer instead of hanging the
// bus waiting for a reply that never comes.
// sys[4] is no longer stubbed - it belongs to the digital resonator, added so
// the feedback loop can be closed against a plant whose Q is known exactly.
sys_bus_stub sys_bus_stub_5 (sys[5]);

// Slot 7 belongs to the parameter sequencer, so it is no longer stubbed. Its
// instantiation is NOT here - it lives further down, immediately above the
// phase shifter it drives. See "PARAMETER SEQUENCER" below and the FIX note
// there for why it had to move.

////////////////////////////////////////////////////////////////////////////////
// Analog mixed signals (PDM analog outputs)
////////////////////////////////////////////////////////////////////////////////

// EDIT (acquisition system cleanup): red_pitaya_ams and red_pitaya_pdm REMOVED.
//
// WHAT THEY DID
// These drove the four slow analogue outputs on the E2 connector (0-1.8 V, made
// by rapidly switching a pin and smoothing it with an external RC filter). This
// experiment does not use them.
//
// WHY REMOVING THEM MATTERS
// red_pitaya_pdm was the design's CRITICAL PATH - the single tightest timing
// path, passing with only 17 picoseconds to spare. It is a sigma-delta
// modulator: a feedback loop that must close within one 8 ns clock tick, so it
// cannot be pipelined without changing its behaviour. Rather than modify a
// working stock module for a feature that is not needed, it is removed.
//
// red_pitaya_ams supplied its configuration and had no other purpose, so it
// goes with it. Its bus slot sys[4] is now stubbed: reads return zero and are
// acknowledged, so software touching 0x40400000 gets a clean answer instead of
// hanging the bus.
//
// The four output pins are driven low, leaving those analogue outputs at 0 V.
//
// TO REVERT: restore the two instantiations, re-add the pdm_cfg declaration,
// remove the tie-off below, and drop the sys[4] stub.
assign dac_pwm_o = 4'b0000;

////////////////////////////////////////////////////////////////////////////////
// ADC IO
////////////////////////////////////////////////////////////////////////////////

// generating ADC clock is disabled
assign adc_clk_o = 2'b10;
//ODDR i_adc_clk_p ( .Q(adc_clk_o[0]), .D1(1'b1), .D2(1'b0), .C(fclk[0]), .CE(1'b1), .R(1'b0), .S(1'b0));
//ODDR i_adc_clk_n ( .Q(adc_clk_o[1]), .D1(1'b0), .D2(1'b1), .C(fclk[0]), .CE(1'b1), .R(1'b0), .S(1'b0));

// ADC clock duty cycle stabilizer is enabled
assign adc_cdcs_o = 1'b1 ;

logic [2-1:0] [14-1:0] adc_dat_raw;

// IO block registers should be used here
// lowest 2 bits reserved for 16bit ADC
always @(posedge adc_clk)
begin
  adc_dat_raw[0] <= adc_dat_i[0][16-1:2];
  adc_dat_raw[1] <= adc_dat_i[1][16-1:2];
end
    
// Internal loopback is registered deliberately. This mode is a software
// diagnostic (Stage 13), not the physical feedback loop. Its amplitude is
// unchanged; only its latency increases by one 125 MHz sample (8 ns).
always @(posedge adc_clk) begin
  if (adc_rstn == 1'b0) begin
    dac_loop[0] <= {14{1'b0}};
    dac_loop[1] <= {14{1'b0}};
  end else begin
    dac_loop[0] <= dac_a;
    dac_loop[1] <= dac_b;
  end
end

// transform into 2's complement (negative slope)
assign adc_dat[0] = digital_loop ? dac_loop[0] : {adc_dat_raw[0][14-1], ~adc_dat_raw[0][14-2:0]};
assign adc_dat[1] = digital_loop ? dac_loop[1] : {adc_dat_raw[1][14-1], ~adc_dat_raw[1][14-2:0]};

////////////////////////////////////////////////////////////////////////////////
// DAC IO
////////////////////////////////////////////////////////////////////////////////

// Sumation of ASG and PID signal perform saturation before sending to DAC 
assign dac_a_sum = asg_dat[0] + pid_dat[0];
assign dac_b_sum = asg_dat[1] + pid_dat[1];

// saturation
assign dac_a = (^dac_a_sum[15-1:15-2]) ? {dac_a_sum[15-1], {13{~dac_a_sum[15-1]}}} : dac_a_sum[14-1:0];
assign dac_b = (^dac_b_sum[15-1:15-2]) ? {dac_b_sum[15-1], {13{~dac_b_sum[15-1]}}} : dac_b_sum[14-1:0];

// output registers + signed to unsigned (also to negative slope)
always @(posedge dac_clk_1x)
begin
  dac_dat_a <= {dac_a[14-1], ~dac_a[14-2:0]};
  dac_dat_b <= {dac_b[14-1], ~dac_b[14-2:0]};
end

// DDR outputs
ODDR oddr_dac_clk          (.Q(dac_clk_o), .D1(1'b0     ), .D2(1'b1     ), .C(dac_clk_2p), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_wrt          (.Q(dac_wrt_o), .D1(1'b0     ), .D2(1'b1     ), .C(dac_clk_2x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_sel          (.Q(dac_sel_o), .D1(1'b1     ), .D2(1'b0     ), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));
ODDR oddr_dac_rst          (.Q(dac_rst_o), .D1(dac_rst  ), .D2(dac_rst  ), .C(dac_clk_1x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_dat [14-1:0] (.Q(dac_dat_o), .D1(dac_dat_b), .D2(dac_dat_a), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));

////////////////////////////////////////////////////////////////////////////////
//  House Keeping
////////////////////////////////////////////////////////////////////////////////

logic [  8-1: 0] exp_p_in , exp_n_in ;
logic [  8-1: 0] exp_p_out, exp_n_out;
logic [  8-1: 0] exp_p_dir, exp_n_dir;

red_pitaya_hk i_hk (
  // system signals
  .clk_i           (adc_clk ),  // clock
  .rstn_i          (adc_rstn),  // reset - active low
  // LED
  //.led_o           (  led_o                      ),  // LED output (EDIT: COMMENTED FOR FLICKER)
  // global configuration
  .digital_loop    (digital_loop),
  // Expansion connector
  .exp_p_dat_i     (exp_p_in ),  // input data
  .exp_p_dat_o     (exp_p_out),  // output data
  .exp_p_dir_o     (exp_p_dir),  // 1-output enable
  .exp_n_dat_i     (exp_n_in ),
  .exp_n_dat_o     (exp_n_out),
  .exp_n_dir_o     (exp_n_dir),
   // System bus
  .sys_addr        (sys[0].addr ),
  .sys_wdata       (sys[0].wdata),
  .sys_wen         (sys[0].wen  ),
  .sys_ren         (sys[0].ren  ),
  .sys_rdata       (sys[0].rdata),
  .sys_err         (sys[0].err  ),
  .sys_ack         (sys[0].ack  )
);

////////////////////////////////////////////////////////////////////////////////
// LED (EDIT: NORMALLY EMPTY BUT COPY + PASTED CODE FOR FLICKER)
////////////////////////////////////////////////////////////////////////////////

reg [27:0]counter = 28'd0;
reg led = 1'b0;

always @ (posedge adc_clk) begin
    counter = counter+1;
    if (counter == 28'd256000000) begin      // 256e6 periods of adc_clock (core clock frequency)
        led = ~led;                          // led will blink with a period of aprox. 2 sec
        counter = 28'd0;                     // reset the counter
    end
end

assign led_o[0] = led;                       // assign the register value to the led output

////////////////////////////////////////////////////////////////////////////////
// GPIO
////////////////////////////////////////////////////////////////////////////////

IOBUF i_iobufp [8-1:0] (.O(exp_p_in), .IO(exp_p_io), .I(exp_p_out), .T(~exp_p_dir) );
IOBUF i_iobufn [8-1:0] (.O(exp_n_in), .IO(exp_n_io), .I(exp_n_out), .T(~exp_n_dir) );

assign gpio.i[15: 8] = exp_p_in;
assign gpio.i[23:16] = exp_n_in;

////////////////////////////////////////////////////////////////////////////////
// oscilloscope
////////////////////////////////////////////////////////////////////////////////

logic trig_asg_out;

////////////////////////////////////////////////////////////////////////////////
//  SCOPE INPUT MULTIPLEXER  (added for the acquisition system)
//
//  Normally the scope sees the two digitised inputs, exactly as before. When
//  the acquisition system's scope-tap feature is switched on (register bit
//  CTRL[3] at 0x40600000), it instead sees an internal signal from partway
//  along the acquisition chain.
//
//  WHY: it lets the EXISTING scope and the notebook that already works with it
//  capture 16384 consecutive samples of the mixer or decimator output, with no
//  new capture hardware at all. That is what makes test-plan stages 3 and 4
//  possible before the memory path is written.
//
//  This multiplexer sits on the SCOPE's input only. It is not in the feedback
//  path, so it cannot affect the 119.87 ns loop delay.
////////////////////////////////////////////////////////////////////////////////
logic [14-1:0] acq_tap_a, acq_tap_b;
logic          acq_tap_en;

logic [14-1:0] scope_dat_a, scope_dat_b;

assign scope_dat_a = acq_tap_en ? acq_tap_a : adc_dat[0];
assign scope_dat_b = acq_tap_en ? acq_tap_b : adc_dat[1];

red_pitaya_scope i_scope (
  // ADC
  .adc_a_i       (scope_dat_a ),  // CH 1 - normally adc_dat[0], or the acquisition tap
  .adc_b_i       (scope_dat_b ),  // CH 2 - normally adc_dat[1], or the acquisition tap
  .adc_clk_i     (adc_clk     ),  // clock
  .adc_rstn_i    (adc_rstn    ),  // reset - active low
  .trig_ext_i    (gpio.i[8]   ),  // external trigger
  .trig_asg_i    (trig_asg_out),  // ASG trigger
  // AXI0 master - still the scope's, used for its channel-A deep captures.
  //
  // AXI1 master - DISCONNECTED. It now belongs to the acquisition system, which
  // uses it to stream I/Q samples into memory. Leaving both modules driving
  // these nets would be a genuine multiple-driver error, not just untidy: the
  // synthesiser would either fail or silently keep one of them.
  //
  // The scope loses its channel-B deep-memory capture as a result. Its normal
  // 16384-sample buffers, which is what the diagnostics actually use, are
  // untouched.
  // BOTH ports now belong to the acquisition system. The scope's deep-memory
  // capture is given up entirely; its normal 16384-sample buffers, which is what
  // the diagnostics actually use, are untouched.
  .axi0_clk_o    (           ),  .axi1_clk_o    (           ),
  .axi0_rstn_o   (           ),  .axi1_rstn_o   (           ),
  .axi0_waddr_o  (           ),  .axi1_waddr_o  (           ),
  .axi0_wdata_o  (           ),  .axi1_wdata_o  (           ),
  .axi0_wsel_o   (           ),  .axi1_wsel_o   (           ),
  .axi0_wvalid_o (           ),  .axi1_wvalid_o (           ),
  .axi0_wlen_o   (           ),  .axi1_wlen_o   (           ),
  .axi0_wfixed_o (           ),  .axi1_wfixed_o (           ),
  .axi0_werr_i   (1'b0       ),  .axi1_werr_i   (1'b0       ),
  .axi0_wrdy_i   (1'b0       ),  .axi1_wrdy_i   (1'b0       ),
  // System bus
  .sys_addr      (sys[1].addr ),
  .sys_wdata     (sys[1].wdata),
  .sys_wen       (sys[1].wen  ),
  .sys_ren       (sys[1].ren  ),
  .sys_rdata     (sys[1].rdata),
  .sys_err       (sys[1].err  ),
  .sys_ack       (sys[1].ack  )
);

////////////////////////////////////////////////////////////////////////////////
//  DAC arbitrary signal generator
////////////////////////////////////////////////////////////////////////////////


red_pitaya_asg i_asg (
   // DAC
  .dac_a_o         (asg_dat[0]  ),  // CH 1
  .dac_b_o         (asg_dat[1]  ),  // CH 2
  .dac_clk_i       (adc_clk     ),  // clock
  .dac_rstn_i      (adc_rstn    ),  // reset - active low
  .trig_a_i        (gpio.i[8]   ),
  .trig_b_i        (gpio.i[8]   ),
  .trig_out_o      (trig_asg_out),
  // System bus
  .sys_addr        (sys[2].addr ),
  .sys_wdata       (sys[2].wdata),
  .sys_wen         (sys[2].wen  ),
  .sys_ren         (sys[2].ren  ),
  .sys_rdata       (sys[2].rdata),
  .sys_err         (sys[2].err  ),
  .sys_ack         (sys[2].ack  )
);

////////////////////////////////////////////////////////////////////////////////
//  Variable phase shift + gain  (EDIT: replaces the MIMO PID controller)
////////////////////////////////////////////////////////////////////////////////
//  WHAT CHANGED HERE AND WHY
//  -------------------------
//  The original baseline instantiated `red_pitaya_pid i_pid` in this spot.
//  We removed that instance (it is preserved, commented out, just below) and
//  put our custom `red_pitaya_phaseshift i_ps` in its place. We chose the PID
//  slot deliberately because the PID's wiring is exactly what we need:
//    * it takes the two ADC channels as inputs   (adc_dat[0], adc_dat[1]);
//    * its two outputs feed the nets pid_dat[0]/pid_dat[1], which the top
//      module already adds into the DAC and saturates:
//          assign dac_a_sum = asg_dat[0] + pid_dat[0];   (see "DAC IO" above)
//    * it sits on system-bus slot sys[3] (base address 0x40300000), which the
//      Jupyter notebook memory-maps to write our registers.
//  So by driving the SAME pid_dat[] nets from the SAME sys[3] bus, nothing
//  downstream (DAC summation, saturation, output registers) had to change.
//
//  NOTE: our module's Verilog file is red_pitaya_phaseshift.v (plain Verilog,
//  like red_pitaya_pid.v). It must be ADDED to the Vivado project or synthesis
//  will not find this module. The module name below is unchanged, so this
//  instantiation is correct regardless of the file's extension.
//
//  Port-by-port meaning of this instance:
////////////////////////////////////////////////////////////////////////////////
//  PARAMETER SEQUENCER  -  times the feedback phase in hardware
//
//  Rewrites the phase shifter's two coefficients at exact times, or on an
//  external trigger edge. Stage 9 measured the software control interval at
//  45 ms against a fabric clock of 8 ns, so timed switching cannot live in
//  Python. See red_pitaya_sequencer.v and SEQUENCER_PLAN.md.
//
//  IDLE AT POWER-ON. Its source bit defaults to 0, so the phase shifter uses
//  its own registers and the board behaves exactly as it did before.
//
//  burst_o and acq_arm_o are brought out but not yet connected: wiring them
//  would need new ports on the signal generator and the acquisition system,
//  which is a separate change. They are left unconnected deliberately, so
//  verify_rtl.py reporting them is expected.
//
//  FIX (Stage 11 build): this block was originally placed up in the system-bus
//  slot section, next to sys_bus_stub_5, which put it BEFORE two of the nets it
//  connects to. SystemVerilog requires a `logic` declaration to precede its
//  first use, and both offenders sat further down this file:
//    * seq_ci / seq_cq / seq_sel  - declared with the phase shifter, just below
//    * exp_p_in                   - declared in the House Keeping section,
//                                   which is also below the old position
//  Rather than scatter the House Keeping declarations, the instantiation moved
//  down here, where everything it touches already exists. Nothing about the
//  connections changed - only the position in the file. sys[7] is still the
//  sequencer's bus slot, and the stub that used to occupy it is still removed.
////////////////////////////////////////////////////////////////////////////////
logic [16-1:0] seq_ci, seq_cq;
logic          seq_sel;
logic          seq_burst, seq_acq_arm;

red_pitaya_sequencer i_seq (
  .clk_i     (adc_clk     ),
  .rstn_i    (adc_rstn    ),
  .ci_o      (seq_ci      ),
  .cq_o      (seq_cq      ),
  .sel_o     (seq_sel     ),
  .burst_o   (seq_burst   ),
  .acq_arm_o (seq_acq_arm ),
  .trig_i    (exp_p_in[0] ),   // expansion header DIO0_P
  .sys_addr  (sys[7].addr ),
  .sys_wdata (sys[7].wdata),
  .sys_wen   (sys[7].wen  ),
  .sys_ren   (sys[7].ren  ),
  .sys_rdata (sys[7].rdata),
  .sys_err   (sys[7].err  ),
  .sys_ack   (sys[7].ack  )
);

red_pitaya_phaseshift i_ps (
   // ---- data path ----
  .clk_i           (adc_clk   ),  // 125 MHz processing clock (same as the rest)
  .rstn_i          (adc_rstn  ),  // active-low reset (same as the rest)
  .dat_a_i         (adc_dat_ps[0]),  // INPUT  CH A: the digitised input - or the
                                    //   digital resonator, when it is enabled
  .dat_b_i         (adc_dat_ps[1]),  // INPUT  CH B: unused in this single-channel build
  .dat_a_o         (pid_dat[0]),  // OUTPUT CH A: phase/gain-shifted result -> DAC CH A
  .dat_b_o         (pid_dat[1]),  // OUTPUT CH B: module drives this to zero
   // ---- coefficients from the sequencer (Stage 11) ----
   //  With seq_sel low - the power-on state - the phase shifter uses its own
   //  software registers and behaves exactly as before.
  .ci_ext_i        (seq_ci    ),
  .cq_ext_i        (seq_cq    ),
  .ext_sel_i       (seq_sel   ),
   // ---- system bus: slot 3 (0x40300000), formerly the PID's ----
  .sys_addr        (sys[3].addr ),  // register address from the CPU
  .sys_wdata       (sys[3].wdata),  // data the CPU writes (coefficients, delay, etc.)
  .sys_wen         (sys[3].wen  ),  // write strobe
  .sys_ren         (sys[3].ren  ),  // read  strobe
  .sys_rdata       (sys[3].rdata),  // data returned to the CPU on a read
  .sys_err         (sys[3].err  ),  // error flag back to the bus (unused, tied 0)
  .sys_ack         (sys[3].ack  )   // acknowledge back to the bus
);

/* ---- Original MIMO PID controller (disabled; kept for reference / revert) ----
red_pitaya_pid i_pid (
   // signals
  .clk_i           (adc_clk   ),  // clock
  .rstn_i          (adc_rstn  ),  // reset - active low
  .dat_a_i         (adc_dat[0]),  // in 1
  .dat_b_i         (adc_dat[1]),  // in 2
  .dat_a_o         (pid_dat[0]),  // out 1
  .dat_b_o         (pid_dat[1]),  // out 2
  // System bus
  .sys_addr        (sys[3].addr ),
  .sys_wdata       (sys[3].wdata),
  .sys_wen         (sys[3].wen  ),
  .sys_ren         (sys[3].ren  ),
  .sys_rdata       (sys[3].rdata),
  .sys_err         (sys[3].err  ),
  .sys_ack         (sys[3].ack  )
);
---------------------------------------------------------------------------- */

////////////////////////////////////////////////////////////////////////////////
// Daisy test code
////////////////////////////////////////////////////////////////////////////////

// dly_clk (fclk[3], 200 MHz from the processor) was only used by the daisy
// chain's input delay lines. Removed with it.

////////////////////////////////////////////////////////////////////////////////
//  ACQUISITION SYSTEM  (Herkenhoff et al., Rev. Sci. Instrum. 92, 103201, Fig. 6a)
//
//  Reads the digitised inputs, shifts the signal of interest down to zero
//  frequency, and averages it down to a manageable rate.
//
//  IMPORTANT - this module only READS adc_dat[]. It is a fan-out of nets that
//  already exist, which costs no time, so it CANNOT affect the feedback path's
//  measured 119.87 ns loop delay. Never insert logic between adc_dat[] and
//  red_pitaya_phaseshift; that is the one change that would undo the timing
//  work done in stage 1.
//
//  Sits on system-bus slot sys[6], base address 0x40600000. Full register map
//  is in the header of red_pitaya_acq.v and in docs/acquisition.md.
//
//  Starts DISABLED at power-on: it does nothing at all until software sets the
//  enable bit, so adding it cannot change existing behaviour.
////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////
//  DIGITAL RESONATOR  -  a stand-in for the trap's detection coil
//
//  Enabled, it replaces the digitised CH A signal with the output of a resonator
//  whose centre frequency and Q software sets exactly, driven by what the board
//  is currently sending out. The feedback loop then closes inside the chip, with
//  no cables and no cryostat, against a plant whose answer is known in advance -
//  which is the only way to tell an instrument fault from a physics one.
//
//  DISABLED AT POWER-ON. While disabled `adc_dat_ps` is `adc_dat` exactly, so
//  the board behaves as it always has. See red_pitaya_resonator.v.
//
//  NOTE ON THE FEEDBACK PATH'S TIMING: the mux below sits between adc_dat and
//  red_pitaya_phaseshift, which the file warns against. A two-input multiplexer
//  is a single LUT and does not pipeline anything, so it costs no clock cycle -
//  the 119.87 ns loop delay is unchanged. CHECK THE TIMING REPORT anyway; that
//  warning exists because this is the one path where being wrong is expensive.
////////////////////////////////////////////////////////////////////////////////
logic signed [14-1:0] reso_dat;
logic                 reso_ena;
SBA_T [MNA-1:0]       adc_dat_ps;

assign adc_dat_ps[0] = reso_ena ? reso_dat : adc_dat[0];
assign adc_dat_ps[1] = adc_dat[1];          // channel B is untouched

red_pitaya_resonator i_reso (
  .clk_i     (adc_clk     ),
  .rstn_i    (adc_rstn    ),
  .dat_i     (dac_a       ),   // what the board is actually sending out
  .dat_o     (reso_dat    ),
  .ena_o     (reso_ena    ),
  .sys_addr  (sys[4].addr ),
  .sys_wdata (sys[4].wdata),
  .sys_wen   (sys[4].wen  ),
  .sys_ren   (sys[4].ren  ),
  .sys_rdata (sys[4].rdata),
  .sys_err   (sys[4].err  ),
  .sys_ack   (sys[4].ack  )
);

//----------------------------------------------------------------------------
//  WHICH MEMORY PORT THE WRITER USES  -  selected by CTRL[8] at run time
//
//  The processor has two write ports into memory, axi0 and axi1. Everything in
//  the acquisition system is identical whichever is used, so if one works and
//  the other does not, the difference is the port and not the logic.
//
//  That question cost most of 2026-07-29. The address counter advanced exactly
//  in step with the sample count, the overflow flag stayed clear, and the memory
//  read back unchanged - at two addresses 340 MB apart. Everything the logic
//  could report said the transfer had worked.
//
//  Answering it by rebuilding is 25 minutes per attempt. Answering it with a
//  register write is seconds, so both ports are wired and CTRL[8] chooses. The
//  cost is a handful of wires: only `wvalid` is gated, so exactly one port ever
//  sees a write, and the unselected one sits idle with valid held low.
//----------------------------------------------------------------------------
logic            acq_axi_clk, acq_axi_rstn, acq_axi_wvalid, acq_axi_wfixed;
logic            acq_axi_werr, acq_axi_wrdy, acq_axi_sel;
logic [ 32-1: 0] acq_axi_waddr;
logic [ 64-1: 0] acq_axi_wdata;
logic [  8-1: 0] acq_axi_wsel;
logic [  4-1: 0] acq_axi_wlen;

//  Address, data and control go to both ports unconditionally - harmless,
//  because a port acts only when its own wvalid is asserted.
assign axi0_clk    = acq_axi_clk;     assign axi1_clk    = acq_axi_clk;
assign axi0_rstn   = acq_axi_rstn;    assign axi1_rstn   = acq_axi_rstn;
assign axi0_waddr  = acq_axi_waddr;   assign axi1_waddr  = acq_axi_waddr;
assign axi0_wdata  = acq_axi_wdata;   assign axi1_wdata  = acq_axi_wdata;
assign axi0_wsel   = acq_axi_wsel;    assign axi1_wsel   = acq_axi_wsel;
assign axi0_wlen   = acq_axi_wlen;    assign axi1_wlen   = acq_axi_wlen;
assign axi0_wfixed = acq_axi_wfixed;  assign axi1_wfixed = acq_axi_wfixed;

//  Only the chosen port is told a write is valid, and only its answers come back.
assign axi0_wvalid = acq_axi_wvalid & ~acq_axi_sel;
assign axi1_wvalid = acq_axi_wvalid &  acq_axi_sel;
assign acq_axi_wrdy = acq_axi_sel ? axi1_wrdy : axi0_wrdy;
assign acq_axi_werr = acq_axi_sel ? axi1_werr : axi0_werr;

red_pitaya_acq i_acq (
  .clk_i           (adc_clk     ),  // 125 MHz processing clock
  .rstn_i          (adc_rstn    ),  // active-low reset
  // tapped inputs (read-only)
  .dat_a_i         (adc_dat_ps[0]),  // digitised IN1 - or the digital resonator
  .dat_b_i         (adc_dat_ps[1]),  // digitised IN2
  // scope tap - feeds the multiplexer in front of i_scope
  .tap_a_o         (acq_tap_a   ),
  .tap_b_o         (acq_tap_b   ),
  .tap_en_o        (acq_tap_en  ),
  // decimated, corrected output stream - also goes to memory below
  .out_i_o         (            ),  // available for future logic; unused here
  .out_q_o         (            ),
  .out_stb_o       (            ),
  // memory-write master. Routed to axi0 or axi1 by CTRL[8] - see below.
  .axi_clk_o       (acq_axi_clk   ),
  .axi_rstn_o      (acq_axi_rstn  ),
  .axi_waddr_o     (acq_axi_waddr ),
  .axi_wdata_o     (acq_axi_wdata ),
  .axi_wsel_o      (acq_axi_wsel  ),
  .axi_wvalid_o    (acq_axi_wvalid),
  .axi_wlen_o      (acq_axi_wlen  ),
  .axi_wfixed_o    (acq_axi_wfixed),
  .axi_werr_i      (acq_axi_werr  ),
  .axi_wrdy_i      (acq_axi_wrdy  ),
  .axi_sel_o       (acq_axi_sel   ),
  // system bus
  .sys_addr        (sys[6].addr ),
  .sys_wdata       (sys[6].wdata),
  .sys_wen         (sys[6].wen  ),
  .sys_ren         (sys[6].ren  ),
  .sys_rdata       (sys[6].rdata),
  .sys_err         (sys[6].err  ),
  .sys_ack         (sys[6].ack  )
);

// EDIT (acquisition system cleanup): red_pitaya_daisy REMOVED.
//
// WHAT IT DID
// Synchronised several Red Pitaya boards over the SATA connector, for multi-board
// experiments. This is a single-board setup, so it has never done anything.
//
// WHY REMOVING IT MATTERS
// It contributed timing paths in the 250 MHz serial clock domain and was the
// source of the "[Synth 8-327] inferring latch for txp_dv_reg" warning. An
// inferred latch is almost always accidental - it is storage that updates
// whenever its input changes rather than on a clock edge, which makes timing
// much harder to guarantee. Removing the module removes the warning and the
// paths together.
//
// Its bus slot sys[5] is now stubbed. The SATA output pins are driven low; the
// SATA input pins are simply left unread.
//
// TO REVERT: restore the instantiation below the SATA pin tie-offs and drop the
// sys[5] stub.
// The SATA pins are a DIFFERENTIAL pair, constrained as DIFF_HSTL_I_18 in the
// pin-assignment file. Driving daisy_p_o and daisy_n_o with two separate constants
// makes them look like two independent single-ended outputs, which contradicts that
// standard and produces a hard DRC ERROR that blocks bitstream generation:
//
//   [DRC IOSTDTYPE-1] I/O port daisy_n_o[0] is Single-Ended but has an IOStandard
//                     of DIFF_HSTL_I_18 which can only support Differential
//
// (This is what happened on the first build after the daisy chain was removed -
//  four such errors, and "Bitgen not run".)
//
// The fix is to keep a real differential output buffer and drive it with a
// constant. OBUFDS produces a proper complementary pair from one logic input, so
// the pins remain a differential pair - electrically valid, standard respected -
// and simply sit at a fixed level. Two buffers, one per SATA lane.
//
// The corresponding INPUT pins (daisy_p_i, daisy_n_i) need nothing: an unused
// input port has no buffer inferred and no standard to contradict.
OBUFDS i_obufds_daisy0 (.O (daisy_p_o[0]), .OB (daisy_n_o[0]), .I (1'b0));
OBUFDS i_obufds_daisy1 (.O (daisy_p_o[1]), .OB (daisy_n_o[1]), .I (1'b0));


endmodule: red_pitaya_top
