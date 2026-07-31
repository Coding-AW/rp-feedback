
# ---------------------------------------------------------------------------
#  Direction-of-rotation plot
#
#  FIX: this used to plot three full rotations, so the dark-to-light colour
#  gradient wrapped three times and every point on the circle ended up with
#  several colours over it - the direction of travel, which is the entire point
#  of these panels, was invisible.
#
#  Now it plots THREE QUARTERS of one rotation, with a marker at the start and
#  one at the end. Less than a full turn means the gradient cannot wrap, so the
#  direction is unambiguous.
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(1, 3, figsize=(14, 4.6))

panels = [(F_SIG,         'reference ON the signal\n(should be a blob)'),
          (F_SIG - DELTA, 'signal ABOVE reference\n(expect ANTICLOCKWISE)'),
          (F_SIG + DELTA, 'signal BELOW reference\n(expect CLOCKWISE)')]

for k, (f_lo, ttl) in enumerate(panels):
    acq.setup(f_lo=f_lo, dec_log2=10, tap_en=True, tap_sel=0, tap_shift=shift)
    time.sleep(0.05)
    a_r, b_r, fs_r = sc.acquire(dec=1)

    # Smooth first. Without this the sum term, comparable in size to the signal,
    # smears every point and hides the circle.
    ai, bi = lowpass(a_r), lowpass(b_r)

    if k == 0:
        n = min(len(ai), 8000)          # no rotation to show, so just show plenty
    else:
        # three quarters of ONE rotation - enough to see the direction, not
        # enough for the colour gradient to wrap
        n = int(0.75 * fs_r / DELTA)
        n = max(200, min(n, len(ai)))

    sc_plot = ax[k].scatter(ai[:n], bi[:n], c=np.arange(n), s=4, cmap='viridis')
    if k > 0:
        ax[k].plot(ai[0], bi[0], 'o', ms=11, mfc='none', mec='k', mew=2)
        ax[k].plot(ai[n-1], bi[n-1], 'x', ms=11, mec='r', mew=2)
        ax[k].annotate('', xy=(ai[n-1], bi[n-1]), xytext=(ai[n-20], bi[n-20]),
                       arrowprops=dict(arrowstyle='-|>', color='r', lw=2))
    ax[k].set_title(ttl); ax[k].set_xlabel('I'); ax[k].set_ylabel('Q')
    ax[k].axhline(0, color='0.8', lw=0.8); ax[k].axvline(0, color='0.8', lw=0.8)
    ax[k].axis('equal'); ax[k].grid(True, alpha=0.4)

plt.suptitle('Open circle = start,  red cross and arrow = end.  '
             'The two right-hand panels must turn OPPOSITE ways.')
plt.tight_layout(); plt.show()

print('Reading these: pick any point on the circle and follow the colour from')
print('dark to light. The middle and right panels must go opposite ways round.')
print('If they turn the SAME way, the sign convention is broken and every')
print('spectrum this instrument produces would come out mirrored.')
