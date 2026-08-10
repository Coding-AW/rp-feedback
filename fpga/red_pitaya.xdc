#
# $Id: red_pitaya.xdc 961 2014-01-21 11:40:39Z matej.oblak $
#
# @brief Red Pitaya location constraints.
#
# @Author Matej Oblak
#
# (c) Red Pitaya  http://www.redpitaya.com
#

############################################################################
# IO constraints                                                           #
############################################################################

### ADC

# ADC data
set_property IOSTANDARD LVCMOS18 [get_ports {adc_dat_i[*][*]}]
set_property IOB        TRUE     [get_ports {adc_dat_i[*][*]}]

# ADC 0 data
set_property PACKAGE_PIN V17     [get_ports {adc_dat_i[0][0]}]
set_property PACKAGE_PIN U17     [get_ports {adc_dat_i[0][1]}]
set_property PACKAGE_PIN Y17     [get_ports {adc_dat_i[0][2]}]
set_property PACKAGE_PIN W16     [get_ports {adc_dat_i[0][3]}]
set_property PACKAGE_PIN Y16     [get_ports {adc_dat_i[0][4]}]
set_property PACKAGE_PIN W15     [get_ports {adc_dat_i[0][5]}]
set_property PACKAGE_PIN W14     [get_ports {adc_dat_i[0][6]}]
set_property PACKAGE_PIN Y14     [get_ports {adc_dat_i[0][7]}]
set_property PACKAGE_PIN W13     [get_ports {adc_dat_i[0][8]}]
set_property PACKAGE_PIN V12     [get_ports {adc_dat_i[0][9]}]
set_property PACKAGE_PIN V13     [get_ports {adc_dat_i[0][10]}]
set_property PACKAGE_PIN T14     [get_ports {adc_dat_i[0][11]}]
set_property PACKAGE_PIN T15     [get_ports {adc_dat_i[0][12]}]
set_property PACKAGE_PIN V15     [get_ports {adc_dat_i[0][13]}]
set_property PACKAGE_PIN T16     [get_ports {adc_dat_i[0][14]}]
set_property PACKAGE_PIN V16     [get_ports {adc_dat_i[0][15]}]

# ADC 1 data
set_property PACKAGE_PIN T17     [get_ports {adc_dat_i[1][0]}]
set_property PACKAGE_PIN R16     [get_ports {adc_dat_i[1][1]}]
set_property PACKAGE_PIN R18     [get_ports {adc_dat_i[1][2]}]
set_property PACKAGE_PIN P16     [get_ports {adc_dat_i[1][3]}]
set_property PACKAGE_PIN P18     [get_ports {adc_dat_i[1][4]}]
set_property PACKAGE_PIN N17     [get_ports {adc_dat_i[1][5]}]
set_property PACKAGE_PIN R19     [get_ports {adc_dat_i[1][6]}]
set_property PACKAGE_PIN T20     [get_ports {adc_dat_i[1][7]}]
set_property PACKAGE_PIN T19     [get_ports {adc_dat_i[1][8]}]
set_property PACKAGE_PIN U20     [get_ports {adc_dat_i[1][9]}]
set_property PACKAGE_PIN V20     [get_ports {adc_dat_i[1][10]}]
set_property PACKAGE_PIN W20     [get_ports {adc_dat_i[1][11]}]
set_property PACKAGE_PIN W19     [get_ports {adc_dat_i[1][12]}]
set_property PACKAGE_PIN Y19     [get_ports {adc_dat_i[1][13]}]
set_property PACKAGE_PIN W18     [get_ports {adc_dat_i[1][14]}]
set_property PACKAGE_PIN Y18     [get_ports {adc_dat_i[1][15]}]

set_property IOSTANDARD DIFF_HSTL_I_18 [get_ports adc_clk_i[*]]
set_property PACKAGE_PIN U18           [get_ports adc_clk_i[1]]
set_property PACKAGE_PIN U19           [get_ports adc_clk_i[0]]

# Output ADC clock
set_property IOSTANDARD LVCMOS18 [get_ports {adc_clk_o[*]}]
set_property SLEW       FAST     [get_ports {adc_clk_o[*]}]
set_property DRIVE      8        [get_ports {adc_clk_o[*]}]
#set_property IOB        TRUE     [get_ports {adc_clk_o[*]}]

set_property PACKAGE_PIN N20 [get_ports {adc_clk_o[0]}]
set_property PACKAGE_PIN P20 [get_ports {adc_clk_o[1]}]

# ADC clock stabilizer
set_property IOSTANDARD  LVCMOS18 [get_ports adc_cdcs_o]
set_property PACKAGE_PIN V18     [get_ports adc_cdcs_o]
set_property SLEW        FAST     [get_ports adc_cdcs_o]
set_property DRIVE       8        [get_ports adc_cdcs_o]

### DAC

# data
set_property IOSTANDARD LVCMOS33 [get_ports {dac_dat_o[*]}]
set_property SLEW       SLOW     [get_ports {dac_dat_o[*]}]
set_property DRIVE      8        [get_ports {dac_dat_o[*]}]
#set_property IOB        TRUE     [get_ports {dac_dat_o[*]}]

set_property PACKAGE_PIN M19 [get_ports {dac_dat_o[0]}]
set_property PACKAGE_PIN M20 [get_ports {dac_dat_o[1]}]
set_property PACKAGE_PIN L19 [get_ports {dac_dat_o[2]}]
set_property PACKAGE_PIN L20 [get_ports {dac_dat_o[3]}]
set_property PACKAGE_PIN K19 [get_ports {dac_dat_o[4]}]
set_property PACKAGE_PIN J19 [get_ports {dac_dat_o[5]}]
set_property PACKAGE_PIN J20 [get_ports {dac_dat_o[6]}]
set_property PACKAGE_PIN H20 [get_ports {dac_dat_o[7]}]
set_property PACKAGE_PIN G19 [get_ports {dac_dat_o[8]}]
set_property PACKAGE_PIN G20 [get_ports {dac_dat_o[9]}]
set_property PACKAGE_PIN F19 [get_ports {dac_dat_o[10]}]
set_property PACKAGE_PIN F20 [get_ports {dac_dat_o[11]}]
set_property PACKAGE_PIN D20 [get_ports {dac_dat_o[12]}]
set_property PACKAGE_PIN D19 [get_ports {dac_dat_o[13]}]

# control
set_property IOSTANDARD LVCMOS33 [get_ports dac_*_o]
set_property SLEW       FAST     [get_ports dac_*_o]
set_property DRIVE      8        [get_ports dac_*_o]
#set_property IOB        TRUE     [get_ports dac_*_o]

set_property PACKAGE_PIN M17 [get_ports dac_wrt_o]
set_property PACKAGE_PIN N16 [get_ports dac_sel_o]
set_property PACKAGE_PIN M18 [get_ports dac_clk_o]
set_property PACKAGE_PIN N15 [get_ports dac_rst_o]

### PWM DAC
set_property IOSTANDARD LVCMOS18 [get_ports {dac_pwm_o[*]}]
set_property SLEW       FAST     [get_ports {dac_pwm_o[*]}]
set_property DRIVE      12       [get_ports {dac_pwm_o[*]}]
# EDIT (acquisition system cleanup): IOB TRUE removed for dac_pwm_o.
#
# This property demands that the signal be driven by a flip-flop placed inside the
# input/output block, which is what makes a pulse-width output's edges land at a
# repeatable time. It only means something for a signal that changes.
#
# red_pitaya_pdm has been removed (it was the design's critical path and drove
# analogue outputs this experiment does not use), so these four pins are now held
# at a constant zero. There is no flip-flop to place, and Vivado reports
#   "[Place 30-722] Terminal 'dac_pwm_o[0]' has IOB constraint set to TRUE, but it
#    is either not connected to a FLOP element..."
#
# The property is therefore removed rather than satisfied artificially. Driving a
# constant through a dummy register purely to keep this constraint happy would add
# logic that exists only to please the tool.
#
# TO REVERT (if the PWM outputs are ever restored): un-comment the line below.
# set_property IOB        TRUE     [get_ports {dac_pwm_o[*]}]

set_property PACKAGE_PIN T10 [get_ports {dac_pwm_o[0]}]
set_property PACKAGE_PIN T11 [get_ports {dac_pwm_o[1]}]
set_property PACKAGE_PIN P15 [get_ports {dac_pwm_o[2]}]
set_property PACKAGE_PIN U13 [get_ports {dac_pwm_o[3]}]

### XADC
set_property IOSTANDARD LVCMOS33 [get_ports {vinp_i[*]}]
set_property IOSTANDARD LVCMOS33 [get_ports {vinn_i[*]}]
#AD0
set_property PACKAGE_PIN C20 [get_ports {vinp_i[1]}]
set_property PACKAGE_PIN B20 [get_ports {vinn_i[1]}]
#AD1
set_property PACKAGE_PIN E17 [get_ports {vinp_i[2]}]
set_property PACKAGE_PIN D18 [get_ports {vinn_i[2]}]
#AD8
set_property PACKAGE_PIN B19 [get_ports {vinp_i[0]}]
set_property PACKAGE_PIN A20 [get_ports {vinn_i[0]}]
#AD9
set_property PACKAGE_PIN E18 [get_ports {vinp_i[3]}]
set_property PACKAGE_PIN E19 [get_ports {vinn_i[3]}]
#V_0
set_property PACKAGE_PIN K9  [get_ports {vinp_i[4]}]
set_property PACKAGE_PIN L10 [get_ports {vinn_i[4]}]

### Expansion connector
set_property IOSTANDARD LVCMOS33 [get_ports {exp_p_io[*]}]
set_property IOSTANDARD LVCMOS33 [get_ports {exp_n_io[*]}]
set_property SLEW       FAST     [get_ports {exp_p_io[*]}]
set_property SLEW       FAST     [get_ports {exp_n_io[*]}]
set_property DRIVE      8        [get_ports {exp_p_io[*]}]
set_property DRIVE      8        [get_ports {exp_n_io[*]}]

set_property PACKAGE_PIN G17 [get_ports {exp_p_io[0]}]
set_property PACKAGE_PIN G18 [get_ports {exp_n_io[0]}]
set_property PACKAGE_PIN H16 [get_ports {exp_p_io[1]}]
set_property PACKAGE_PIN H17 [get_ports {exp_n_io[1]}]
set_property PACKAGE_PIN J18 [get_ports {exp_p_io[2]}]
set_property PACKAGE_PIN H18 [get_ports {exp_n_io[2]}]
set_property PACKAGE_PIN K17 [get_ports {exp_p_io[3]}]
set_property PACKAGE_PIN K18 [get_ports {exp_n_io[3]}]
set_property PACKAGE_PIN L14 [get_ports {exp_p_io[4]}]
set_property PACKAGE_PIN L15 [get_ports {exp_n_io[4]}]
set_property PACKAGE_PIN L16 [get_ports {exp_p_io[5]}]
set_property PACKAGE_PIN L17 [get_ports {exp_n_io[5]}]
set_property PACKAGE_PIN K16 [get_ports {exp_p_io[6]}]
set_property PACKAGE_PIN J16 [get_ports {exp_n_io[6]}]
set_property PACKAGE_PIN M14 [get_ports {exp_p_io[7]}]
set_property PACKAGE_PIN M15 [get_ports {exp_n_io[7]}]

#set_property PULLDOWN TRUE [get_ports {exp_p_io[0]}]
#set_property PULLDOWN TRUE [get_ports {exp_n_io[0]}]
#set_property PULLUP   TRUE [get_ports {exp_p_io[7]}]
#set_property PULLUP   TRUE [get_ports {exp_n_io[7]}]

set_property PACKAGE_PIN T12 [get_ports {daisy_p_o[0]}]
set_property PACKAGE_PIN U12 [get_ports {daisy_n_o[0]}]
set_property PACKAGE_PIN U14 [get_ports {daisy_p_o[1]}]
set_property PACKAGE_PIN U15 [get_ports {daisy_n_o[1]}]
set_property PACKAGE_PIN P14 [get_ports {daisy_p_i[0]}]
set_property PACKAGE_PIN R14 [get_ports {daisy_n_i[0]}]
set_property PACKAGE_PIN N18 [get_ports {daisy_p_i[1]}]
set_property PACKAGE_PIN P19 [get_ports {daisy_n_i[1]}]

### LED
set_property IOSTANDARD LVCMOS33 [get_ports {led_o[*]}]
set_property SLEW       SLOW     [get_ports {led_o[*]}]
set_property DRIVE      4        [get_ports {led_o[*]}]

set_property PACKAGE_PIN F16     [get_ports {led_o[0]}]
set_property PACKAGE_PIN F17     [get_ports {led_o[1]}]
set_property PACKAGE_PIN G15     [get_ports {led_o[2]}]
set_property PACKAGE_PIN H15     [get_ports {led_o[3]}]
set_property PACKAGE_PIN K14     [get_ports {led_o[4]}]
set_property PACKAGE_PIN G14     [get_ports {led_o[5]}]
set_property PACKAGE_PIN J15     [get_ports {led_o[6]}]
set_property PACKAGE_PIN J14     [get_ports {led_o[7]}]

############################################################################
# Clock constraints                                                        #
############################################################################

#NET "adc_clk" TNM_NET = "adc_clk";
#TIMESPEC TS_adc_clk = PERIOD "adc_clk" 125 MHz;

create_clock -period 8.000 -name adc_clk [get_ports adc_clk_i[1]]

set_input_delay -clock adc_clk 3.400 [get_ports adc_dat_i[*][*]]

#create_clock -period 4.000 -name rx_clk  [get_ports daisy_p_i[1]]

############################################################################
# EDIT (Imperial CCM internship): clock names corrected.
#
# THE PROBLEM
# -----------
# Every false-path constraint in this section named a clock that does not
# exist in this design - dac_clk_o, dac_clk_1x, dac_clk_2x, dac_clk_2p,
# ser_clk, pdm_clk. Vivado reported "[Vivado 12-627] No clocks matched" and
# "[Vivado 12-4739] set_false_path: No valid object(s) found", then carried on
# without them. Roughly 30 constraints were doing nothing at all.
#
# The real generated-clock names are taken from the net names at the PLL
# outputs in red_pitaya_top.sv, so they are:
#
#     pll_adc_clk      125 MHz   ADC / main processing domain
#     pll_dac_clk_1x   125 MHz   DAC output domain
#     pll_dac_clk_2x   250 MHz   DAC double-rate domain
#     pll_dac_clk_2p   250 MHz   DAC double-rate, -45 degree phase
#     pll_ser_clk      250 MHz   fast serial (SATA daisy chain)
#     pll_pwm_clk      250 MHz   PWM / slow analogue outputs
#
# ("adc_clk" IS a real clock - it is the 125 MHz oscillator arriving on the
#  input pin. It is the PLL's *input*. The fabric runs on pll_adc_clk, which
#  the PLL generates from it. Constraints that meant "the processing domain"
#  and said "adc_clk" were therefore aiming at the wrong object even when the
#  name resolved.)
#
# THE FIX
# -------
# (a) One clock-group statement replaces all the "clk_fpga_0 -> something"
#     lines. The processor's clocks come from a completely separate PLL
#     inside the Zynq processing system and have no fixed phase relationship
#     to the external 125 MHz oscillator, so nothing crossing between the two
#     families should ever be timed. Writing it as a group is also robust:
#     -include_generated_clocks picks up every clock derived from the
#     oscillator automatically, so this does not silently rot if a clock is
#     renamed or added later.
#
# (b) Explicit false paths for the DAC reset crossing from the 125 MHz DAC
#     domain into the two 250 MHz DAC domains. This is what the original
#     "dac_clk_o -> dac_clk_2x/2p" lines were for.
#
# DELIBERATELY NOT RESTORED: the original "adc_clk -> DAC" false paths.
# pll_adc_clk and pll_dac_clk_1x are both 125 MHz from the same PLL with the
# same phase, so that crossing is genuinely synchronous and Vivado can time it
# properly - and it already passes with 3.1 ns to spare. Leaving it timed
# keeps a real check in place instead of switching it off.
############################################################################

# CLOCK GROUPS AND THE ADC MULTICYCLE HAVE MOVED to red_pitaya_impl.xdc,
# which is marked "not used in synthesis".
#
# WHY: both can only be evaluated once the Zynq processing system has been
# elaborated, which does not happen until implementation. Reading them during
# synthesis produced either
#     [Vivado 12-4739] set_clock_groups: No valid object(s) found
# or, when guarded with a Tcl "if" to avoid that,
#     [Designutils 20-1307] Command 'if' is not supported in the xdc file
# because an XDC file is a restricted subset of Tcl with no control flow.
#
# A separate file that synthesis never reads solves both, with no conditionals.


set_false_path -from [get_clocks pll_dac_clk_1x] -to [get_clocks pll_dac_clk_2x]
set_false_path -from [get_clocks pll_dac_clk_1x] -to [get_clocks pll_dac_clk_2p]

