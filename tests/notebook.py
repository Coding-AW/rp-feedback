"""Run notebook cells against mock hardware, without a Red Pitaya.

The notebooks are standalone, so the tests execute their cells directly rather
than importing a package. Cells are selected by their code-cell number, the
same number shown in each cell's heading ("## 12 — ...").
"""
import contextlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'notebooks' / 'test_noise_passive_feedback.ipynb'
HIGH_K = ROOT / 'notebooks' / 'resonator_coil_manual_high_k.ipynb'

# Cell groups of the main notebook used by several test files.
LIBRARY = (1, 2, 3)                       # configuration, imports, shared helpers
HARDWARE = LIBRARY + (5, 6, 7, 8, 9, 10)  # plus register classes and capture()


def code_cells(path=MAIN):
    """Code-cell sources keyed by their number in the notebook (1, 2, ...)."""
    book = json.loads(path.read_text(encoding='utf-8'))
    code = [cell for cell in book['cells'] if cell['cell_type'] == 'code']
    return {number: ''.join(cell['source']) for number, cell in enumerate(code, 1)}


def run_cells(numbers, namespace=None, path=MAIN):
    """Execute the given code cells, in order, into one namespace."""
    ns = {} if namespace is None else namespace
    cells = code_cells(path)
    with contextlib.redirect_stdout(io.StringIO()):
        for number in numbers:
            exec(compile(cells[number], '%s cell %d' % (path.name, number), 'exec'), ns)
    return ns


class _LoggedMemory(bytearray):
    """Register memory that records every 32-bit write as (offset, value)."""

    def __init__(self, size, log):
        super().__init__(size)
        self.log = log

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if isinstance(key, slice):
            self.log.append((key.start, int.from_bytes(bytes(value), 'little')))


class MemoryTransport(object):
    """Stand-in for DevMemTransport: plain memory instead of /dev/mem."""

    def __init__(self, base, span):
        self.base = base
        self.fd = None
        self.write_log = []
        self.m = _LoggedMemory(span, self.write_log)

    def close(self):
        pass


class QualifiedMemoryTransport(MemoryTransport):
    """Memory transport whose acquisition block reports the qualified build ID."""

    def __init__(self, base, span):
        MemoryTransport.__init__(self, base, span)
        if base == 0x40600000:                       # build ID register 0x48
            self.m[0x48:0x4C] = (0xFE76AE09).to_bytes(4, 'little')
            self.write_log.clear()


def mock_hardware(transport=MemoryTransport):
    """Configuration, helpers and register classes wired to memory registers."""
    ns = run_cells(HARDWARE)
    ns['TRANSPORT_FACTORY'] = transport
    return ns
