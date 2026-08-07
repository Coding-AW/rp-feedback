# -*- coding: utf-8 -*-
# ============================================================================
#  THE ATLAS, IN THE PAPER'S FORMAT  -  plotting only, no re-measurement.
#  Safe to re-run on data already in memory: it reads M_Q, M_DF, M_T, LINEAR,
#  GAINS_DB and PHIS and writes nothing.
# ============================================================================
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter, LogLocator, MaxNLocator

plt.close('all')

CUT_GAINS_DB    = [4.0, 1.0, -2.0]
CUT_COLOURS     = ['#EECC66', '#EE8866', '#77AADD']
MARK_COMPRESSED = True

# The narrowing phase, read off the highest fully stable gain row.
_full = [i for i in range(len(GAINS_DB)) if np.isfinite(M_Q[i]).all()]
PHASE_REF = PHIS[int(np.nanargmax(M_Q[_full[-1]]))] if _full else 0.0


def _edges(c):
    c = np.asarray(c, dtype=float)
    e = np.empty(c.size + 1)
    e[1:-1] = 0.5 * (c[1:] + c[:-1])
    e[0]    = c[0]  - 0.5 * (c[1] - c[0])
    e[-1]   = c[-1] + 0.5 * (c[-1] - c[-2])
    return e


def _phase_axis(M):
    """Wrap to -180..180 about PHASE_REF, sort, and close the periodic seam."""
    x = (PHIS - PHASE_REF + 180.0) % 360.0 - 180.0
    o = np.argsort(x)
    x, M = x[o], M[:, o]
    return (np.concatenate([x, [x[0] + 360.0]]),
            np.concatenate([M, M[:, :1]], axis=1))


def _freq_unit(vmax):
    """Pick Hz / kHz / MHz so the tick labels stay short.

    This is what was wrong with the first version: the shift on this plant runs
    to +-160 kHz, so in Hz the colourbar read '-160000 -120000 -80000 ...' and
    the labels collided with each other, with the panel letter and with the
    title above them. Nine ticks of six digits will not fit over a 4-inch axis
    in any font. Scale the data instead of shrinking the text."""
    if vmax >= 1e6:  return 1e6, 'MHz'
    if vmax >= 1e3:  return 1e3, 'kHz'
    return 1.0, 'Hz'


def paper_atlas():
    plt.rcParams.update({'font.family': 'serif', 'mathtext.fontset': 'cm',
                         'axes.linewidth': 0.8, 'font.size': 10.5,
                         'xtick.direction': 'out', 'ytick.direction': 'out'})
    x,  Q   = _phase_axis(M_Q)
    _,  DF  = _phase_axis(M_DF)
    _,  LIN = _phase_axis(np.where(LINEAR, 1.0, np.nan))
    scale, unit = _freq_unit(np.nanmax(np.abs(M_DF)))
    DF = DF / scale
    xe, ye = _edges(x), _edges(GAINS_DB)
    deg = FuncFormatter(lambda v, p: u'%d°' % int(round(v)))

    fig = plt.figure(figsize=(9.6, 6.9))
    # More room all round than before: wider gutter between the columns so the
    # right-hand y label cannot reach the left panel, and a taller colourbar
    # strip so its ticks and its title are not in the same place.
    gs = GridSpec(3, 2, height_ratios=[0.052, 1.0, 0.46],
                  hspace=0.16, wspace=0.42,
                  left=0.105, right=0.975, top=0.885, bottom=0.085)

    for col, M, label, is_log in (
            (0, Q,  u'$Q$', True),
            (1, DF, u'$\\Delta\\nu_\\mathrm{res}$ / %s' % unit, False)):
        cax = fig.add_subplot(gs[0, col])
        ax  = fig.add_subplot(gs[1, col])
        axc = fig.add_subplot(gs[2, col])
        D = np.ma.masked_invalid(M)

        if is_log:
            pos = M[np.isfinite(M) & (M > 0)]
            norm = mcolors.LogNorm(vmin=pos.min(), vmax=pos.max()) if pos.size else None
        else:
            lim = np.nanmax(np.abs(M))
            norm = mcolors.Normalize(vmin=-lim, vmax=lim)

        im = ax.pcolormesh(xe, ye, D, norm=norm, cmap='viridis')
        set_bg(ax, 'black')
        ax.set_xlim(-180, 180); ax.set_ylim(ye[0], ye[-1])
        ax.set_xticks([-180, -90, 0, 90, 180]); ax.set_xticklabels([])
        ax.set_ylabel(u'Fb. gain / dB')

        cb = fig.colorbar(im, cax=cax, orientation='horizontal')
        cax.xaxis.set_ticks_position('top')
        cax.xaxis.set_label_position('top')
        # FEW ticks, explicitly. Matplotlib's default count is chosen for a tall
        # vertical colourbar; on a horizontal one it packs in far too many.
        if is_log:
            cb.locator = LogLocator(base=10.0, numticks=4)
        else:
            cb.locator = MaxNLocator(nbins=5, symmetric=True, prune=None)
        cb.update_ticks()
        cax.tick_params(labelsize=9, pad=2)
        cax.set_xlabel(label, labelpad=7)

        if is_log and MARK_COMPRESSED:
            ii, jj = np.where(np.isfinite(M) & ~np.isfinite(LIN))
            if len(ii):
                ax.plot(x[jj], GAINS_DB[ii], 'o', mfc='none', mec='w',
                        ms=4, mew=0.9, linestyle='none')
                ax.set_xlim(-180, 180); ax.set_ylim(ye[0], ye[-1])

        for gdb, colour in zip(CUT_GAINS_DB, CUT_COLOURS):
            i = int(np.argmin(np.abs(GAINS_DB - gdb)))
            ax.axhline(GAINS_DB[i], color=colour, ls='--', lw=1.1, dashes=(5, 3))
            axc.plot(x, M[i], '-', color=colour, lw=1.2)

        axc.set_xlim(-180, 180); axc.set_xticks([-180, -90, 0, 90, 180])
        axc.xaxis.set_major_formatter(deg)
        axc.set_xlabel(u'Feedback phase')
        axc.grid(color='0.75', lw=0.6); axc.set_axisbelow(True)
        if is_log:
            axc.set_yscale('log'); axc.set_ylabel(u'$Q$')
        else:
            axc.set_ylabel(u'$\\Delta\\nu_\\mathrm{res}$ / %s' % unit)
            axc.yaxis.set_major_locator(MaxNLocator(nbins=5, symmetric=True))

    # Panel letters, clear of the colourbar tick labels above the axes.
    fig.text(0.012, 0.962, '(a)', fontsize=12)
    fig.text(0.522, 0.962, '(b)', fontsize=12)
    plt.show()


paper_atlas()
print('black = self-oscillation (or unresolved). White rings = too loud to be a')
print('linear measurement. Both are drawn, neither is fitted.')
print('phase axis is relative to %.0f deg (the narrowing phase, taken from the'
      % PHASE_REF)
print('atlas itself), so 0 on the plots is that phase.')
print('gain cuts at %s dB (snapped to the grid).'
      % ', '.join('%+.1f' % g for g in CUT_GAINS_DB))

# -----------------------------------------------------------------------------
#  T_eff / T0 - not in the paper, so it keeps its own panel rather than being
#  forced into a layout designed for two quantities.
# -----------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(6.2, 4.2))
D = np.ma.masked_invalid(M_T)
pos = M_T[np.isfinite(M_T) & (M_T > 0)]
xT, MT = _phase_axis(M_T)
im = ax.pcolormesh(_edges(xT), _edges(GAINS_DB), np.ma.masked_invalid(MT),
                   norm=(mcolors.LogNorm(vmin=pos.min(), vmax=pos.max())
                         if pos.size else None), cmap='viridis')
set_bg(ax, 'black')
ax.set_xlim(-180, 180); ax.set_xticks([-180, -90, 0, 90, 180])
ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: u'%d\u00b0' % int(round(v))))
ax.set_xlabel(u'Feedback phase'); ax.set_ylabel(u'Fb. gain / dB')
ax.set_title(u'$T_\\mathrm{eff}/T_0$  (the map the paper never drew)')
cb2 = plt.colorbar(im, ax=ax)
cb2.locator = LogLocator(base=10.0, numticks=5); cb2.update_ticks()
plt.tight_layout(); plt.show()
