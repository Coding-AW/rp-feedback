############################################################################
# EDIT (Imperial CCM internship): dead constraints removed.
#
# Everything that was in this section named an object that does not exist in
# this design, so Vivado printed a warning and silently ignored the line. A
# constraint that is ignored is worse than no constraint, because the report
# looks like the design is constrained when it is not.
#
# 1. set_property LOC XADC_X0Y0 [get_cells i_ams/XADC_inst]
#    -> "[Vivado 12-180] No cells matched 'i_ams/XADC_inst'"
#    The XADC no longer lives inside i_ams; it is inside the block design at
#    ps/system_i/xadc. The constraint is also unnecessary: this device has
#    exactly one XADC site, so there is nothing for the placer to get wrong.
#    Removed rather than retargeted.
#
# 2. The false-path constraints below named clocks that do not exist:
#       dac_clk_out, dac_2clk_out, dac_2ph_out, ser_clk_out, par_clk
#    -> "[Vivado 12-627] No clocks matched ..."
#    The real generated-clock names in this design come from the net names at
#    the PLL outputs in red_pitaya_top.sv:
#       pll_adc_clk, pll_dac_clk_1x, pll_dac_clk_2x, pll_dac_clk_2p,
#       pll_ser_clk, pll_pwm_clk
#    The corrected constraints are consolidated in the other constraint file
#    (sdc/red_pitaya.xdc) so there is ONE place that defines clock
#    relationships, rather than two files disagreeing with each other.
#
# The SATA pin properties below are real and are kept unchanged.
############################################################################

### SATA connector
set_property IOSTANDARD DIFF_HSTL_I_18 [get_ports {daisy_p_o[*]}]
set_property IOSTANDARD DIFF_HSTL_I_18 [get_ports {daisy_n_o[*]}]
set_property IOSTANDARD DIFF_HSTL_I_18 [get_ports {daisy_p_i[*]}]
set_property IOSTANDARD DIFF_HSTL_I_18 [get_ports {daisy_n_i[*]}]