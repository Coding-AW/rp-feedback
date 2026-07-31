
# ---------------------------------------------------------------------------
#  Remove the circular-buffer wrap from captures
#
#  The scope writes into a ring buffer and keeps writing until the capture ends,
#  so the oldest sample is wherever the write pointer stopped - NOT at index 0.
#  Reading from the start of the buffer therefore returns a rotated copy of the
#  time series, with one discontinuity in the middle. That is the single step
#  visible in the Step 2 traces.
#
#  Register 0x18 holds the current write pointer. Rolling the arrays by it puts
#  the samples back in time order.
#
#  Run this cell once, after the Scope class has been created. It replaces the
#  acquire method on the existing object.
# ---------------------------------------------------------------------------
def _acquire_unwrapped(self, dec=1, n=NMAX):
    self.w(0x14, dec)       # scope decimation
    self.w(0x10, n - 1)     # samples to record
    self.w(0x00, 2)         # reset the acquisition engine
    self.w(0x00, 1)         # arm
    self.w(0x04, 1)         # trigger now, from software
    t0 = time.time()
    while self.r(0x04) != 0:
        if time.time() - t0 > 1.0:
            break
    time.sleep(0.005)

    a = self._buf(BUF_A, n)
    b = self._buf(BUF_B, n)

    if n == NMAX:                       # only meaningful for a full-buffer capture
        wp = self.r(0x18) & (NMAX - 1)  # where the writing stopped
        a = np.roll(a, -wp)             # oldest sample first
        b = np.roll(b, -wp)

    return a, b, FS_CLK / dec


import types
sc.acquire = types.MethodType(_acquire_unwrapped, sc)
print('scope captures will now be un-wrapped (write pointer read from 0x18)')
print('the single step in the middle of the traces should disappear')
