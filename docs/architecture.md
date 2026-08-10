# Architecture

The design contains two deliberately separate paths clocked from the Red Pitaya
125 MHz fabric clock.

```text
                         feedback (controls the experiment)
IN1 ─► ADC ─► delay/phase/gain ───────────────────────────► OUT1/OUT2
        │
        └► DDS mixer ─► CIC decimator ─► FIR correction ─► DMA ─► DDR
                         acquisition (observes only)
```

The feedback path implements fractional delay and complex gain. The acquisition
path down-converts a selected ADC input, decimates it, corrects CIC droop, and
writes interleaved I/Q samples through a Zynq high-performance AXI port.

An optional digital resonator can replace the physical ADC input for safe,
repeatable end-to-end tests. A parameter sequencer applies deterministic changes
without relying on Linux scheduling.

Project-owned HDL is flat under `fpga/`. Everything else used for synthesis
comes from the pinned RedPitaya-FPGA v0.94 baseline during setup. See
[acquisition.md](acquisition.md) and [feedback.md](feedback.md) for implementation
detail.
