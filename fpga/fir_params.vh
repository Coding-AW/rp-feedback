// ==========================================================================
//  Filter sizes - GENERATED FILE, DO NOT EDIT
//
//  Retained with fir_coeffs.vh as the qualified handover parameter set; this is the single
//  source of truth for these numbers. Included by red_pitaya_acq_fir.v
//  (which builds the filter) and red_pitaya_acq.v (which decides when the
//  filter is too slow for the chosen decimation and must be bypassed).
// ==========================================================================

localparam integer GEN_NTAPS        = 309;
localparam integer GEN_NHALF        = 155;   // unique coefficients stored
localparam integer GEN_COEFW        = 18;
localparam integer GEN_COEF_FRAC    = 17;
localparam integer GEN_MIN_DEC_LOG2 = 8;   // R = 256 and above
