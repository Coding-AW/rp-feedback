/**
 * @brief IQ mixer (complex downconverter) for the acquisition system.
 *
 * @Author Alex (Imperial CCM internship) - custom module
 *
 * (c) Red Pitaya  http://www.redpitaya.com  (baseline v0.94)
 *
 * Part of the acquisition system of Herkenhoff et al., Rev. Sci. Instrum. 92,
 * 103201 (2021).  See Fig. 6a: the two multiplier symbols immediately after
 * the ADC tap, fed by "Local osc." and feeding the two CIC filters.
 *
 * ===========================================================================
 *  WHAT THIS MODULE DOES
 * ===========================================================================
 *  It multiplies the incoming ADC samples by the two local-oscillator
 *  references produced by red_pitaya_acq_dds, and nothing else.  Two hardware
 *  multipliers, that is the entire module.
 *
 *  WHY multiplication shifts frequency:  the product-to-sum identity
 *
 *      cos(a) * cos(b) = 0.5*cos(a-b) + 0.5*cos(a+b)
 *
 *  says that multiplying a signal at frequency f_sig by a reference at f_lo
 *  produces TWO new components: one at the DIFFERENCE (f_sig - f_lo) and one
 *  at the SUM (f_sig + f_lo).  Setting f_lo = 40 MHz and f_sig = 40 MHz + a
 *  few kHz puts the difference term at a few kHz - right down at baseband,
 *  where a modest sample rate can represent it - while the sum term lands at
 *  80 MHz.  The CIC filter in the next stage removes the sum term.
 *
 *  (Strictly, at f_clk = 125 MSPS the 80 MHz sum term appears as an alias at
 *  125 - 80 = 45 MHz.  This is harmless: it is still hundreds of times further
 *  from 0 Hz than our few-kHz signal, so the decimating filter annihilates it.)
 *
 * ===========================================================================
 *  WHY TWO MULTIPLIERS AND NOT ONE
 * ===========================================================================
 *  With a single reference you cannot tell f_lo + 1 kHz from f_lo - 1 kHz:
 *  both give a 1 kHz difference term.  The resonator lineshape is not
 *  symmetric about the local oscillator in general, and the ion dip sits on
 *  one specific side of it, so that ambiguity would be fatal.
 *
 *  Using two references 90 degrees apart and keeping both products gives a
 *  COMPLEX baseband signal z = I + jQ.  A complex signal has a two-sided
 *  spectrum, so positive and negative offsets from the local oscillator stay
 *  distinct.  This is why every path downstream of here is duplicated: one
 *  copy for I, one for Q, all the way to the 64-bit words written to memory.
 *
 *  SIGN CONVENTION: Q uses MINUS sin(theta).  With that choice, an input at
 *  f_lo + df comes out as z = exp(+j*2*pi*df*t), i.e. a POSITIVE frequency in
 *  the acquired spectrum corresponds to a signal ABOVE the local oscillator -
 *  the convention every FFT plotting routine assumes.  Dropping the minus sign
 *  would simply mirror the spectrum left-to-right, which is a very easy bug to
 *  stare past, hence this note.
 *
 * ===========================================================================
 *  WORD WIDTHS AND WHY THE OUTPUT IS 24 BITS
 * ===========================================================================
 *  ADC sample     : 14-bit signed, range +-8191
 *  LO reference   : 16-bit signed, peak +-32767  (i.e. represents +-1.0)
 *  Raw product    : 30-bit signed, peak ~2^28
 *
 *  A "correct" rescaling back to ADC units would shift right by 15 (dividing
 *  by the LO peak amplitude).  We deliberately shift by only SHIFT = 6, which
 *  keeps 9 extra bits BELOW the original ADC least-significant bit.
 *
 *  Those bits are not fake precision.  The decimating filter that follows
 *  averages tens to thousands of samples together, and averaging genuinely
 *  recovers resolution below one ADC step (each factor of 4 in averaging buys
 *  one extra bit).  Truncating to 14 bits here would throw that away before it
 *  could be earned.  Keeping 24 bits matches the width shown on the datapath
 *  in Fig. 6a of the paper.
 *
 *  Headroom check: peak product 2^28 >> 6 = 2^22, against a 24-bit signed
 *  limit of 2^23.  One full bit of margin, so the mixer can never overflow
 *  even with a full-scale input.
 */

`timescale 1ns / 1ps

module red_pitaya_acq_mixer #(
  parameter integer DWI   = 14,   // ADC sample width, signed
  parameter integer DWL   = 16,   // local-oscillator width, signed
  parameter integer DWO   = 24,   // output width per channel, signed
  parameter integer SHIFT = 6     // right shift applied to the raw product
)(
  // ---- clock and reset ----
  input                          clk_i    ,  //!< 125 MHz processing clock
  input                          rstn_i   ,  //!< active-LOW synchronous reset

  // ---- inputs ----
  input      signed [ DWI-1: 0]  dat_i    ,  //!< tapped ADC samples
  input      signed [ DWL-1: 0]  lo_cos_i ,  //!< in-phase   reference from the DDS
  input      signed [ DWL-1: 0]  lo_sin_i ,  //!< quadrature reference from the DDS

  // ---- outputs: the complex baseband pair ----
  output reg signed [ DWO-1: 0]  i_dat_o  ,  //!< I = x * cos(theta)
  output reg signed [ DWO-1: 0]  q_dat_o     //!< Q = x * -sin(theta)
);

//---------------------------------------------------------------------------------
//  Stage 1 - the multiplies.
//
//  Registering the product on its own is what lets Vivado absorb each multiply
//  into a single DSP48E1 slice using its internal pipeline register, rather than
//  building a slow multiplier out of general logic.  Two DSP48E1 slices total;
//  the device has 60 free.
//
//  14 x 16 bits fits comfortably inside the DSP48E1's native 25 x 18 multiplier,
//  so no decomposition into partial products is needed and the result is exact.
//---------------------------------------------------------------------------------
reg signed [ DWI+DWL-1: 0] prod_i;   // 30 bits
reg signed [ DWI+DWL-1: 0] prod_q;   // 30 bits

always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    prod_i <= {(DWI+DWL){1'b0}};
    prod_q <= {(DWI+DWL){1'b0}};
  end else begin
    prod_i <=  dat_i * lo_cos_i;      // in-phase   product
    prod_q <= -(dat_i * lo_sin_i);    // quadrature product, negated (see note above)
  end
end

//---------------------------------------------------------------------------------
//  Stage 2 - rescale to the 24-bit datapath width.
//
//  >>> is the ARITHMETIC right shift: it copies the sign bit inwards, so
//  negative numbers stay negative.  Using the plain >> here would corrupt every
//  negative sample, which is a classic and very confusing bug because the
//  positive half of the waveform still looks correct on a plot.
//
//  This truncates rather than rounds.  Truncation adds a tiny DC offset of half
//  a least-significant bit.  At 24 bits that offset is ~120 dB below full scale
//  and sits exactly at 0 Hz, where the local oscillator leakage already puts a
//  much larger feature, so rounding logic would buy nothing here.
//---------------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (rstn_i == 1'b0) begin
    i_dat_o <= {DWO{1'b0}};
    q_dat_o <= {DWO{1'b0}};
  end else begin
    i_dat_o <= prod_i >>> SHIFT;
    q_dat_o <= prod_q >>> SHIFT;
  end
end

endmodule
