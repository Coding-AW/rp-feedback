#!/usr/bin/env python3
"""
Check the Verilog for mistakes that only show up 90 seconds into a build.

    python3 tools/verify_rtl.py

WHY THIS EXISTS
---------------
On 2026-07-29 an edit added a port to a module by string replacement. The
replacement did not match - the file said

    output                    axi_wfixed_o,

and the pattern looked for

    output                    axi_wfixed_o   ,

with different spacing. Nothing complained. The *use* of the port was added
successfully, so the design now referred to a port that did not exist, and
synthesis failed:

    [Synth 8-448] named port connection 'axi_sel_o' does not exist for
                  instance 'i_acq' of module 'red_pitaya_acq'

That is a 90-second wait to be told something a one-second check could have
caught. This is that check.

WHAT IT CHECKS
--------------
  1. Every module named in an instantiation exists.
  2. Every named port connection - the `.foo(bar)` form - names a port the
     target module actually has.   <- the one that bit
  3. Every signal driven by a continuous assignment is declared somewhere in
     the same module: as a port, wire, reg or logic.
  4. Ports of a module that are never connected in an instantiation, reported
     as information rather than as an error - Vivado allows it, and it is
     sometimes deliberate, but an unexpected one usually means a rename that
     was only half done.

WHAT IT IS NOT
--------------
It is not a compiler. It does not check widths, types, timing, or whether the
logic is correct. It reads the text and checks that the names line up. Passing
here does not mean the design works; failing here means it definitely will not
build, which is worth knowing before the 25 minutes rather than after.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RTL_DIRS = [os.path.join(ROOT, 'fpga')]

#  Words that look like a module instantiation but are not.
KEYWORDS = set("""
module endmodule input output inout wire reg logic assign always initial begin end
if else case endcase for while generate endgenerate genvar parameter localparam
function endfunction task endtask posedge negedge integer real time signed unsigned
default and or not xor nand nor xnor buf bufif0 bufif1 notif0 notif1 pullup pulldown
supply0 supply1 tri wand wor tri0 tri1 triand trior trireg vectored scalared
specify endspecify table endtable primitive endprimitive defparam
typedef struct union enum interface endinterface package endpackage import export
return break continue fork join disable wait force release assign deassign
""".split())


def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def read_sources():
    out = {}
    for d in RTL_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith('.v') or name.endswith('.sv'):
                path = os.path.join(d, name)
                with open(path, 'r', errors='replace') as fh:
                    out[path] = strip_comments(fh.read())
    return out


# ---------------------------------------------------------------------------
def module_ports(body):
    """Port names of one module, from the header and from any later
    `input`/`output`/`inout` declarations."""
    ports = set()
    header = body.split(');', 1)[0]
    for m in re.finditer(r'\b(?:input|output|inout)\b([^;,()]*(?:\([^)]*\))?[^;,]*)', header):
        for name in re.findall(r'(\w+)\s*(?:,|$)', m.group(1)):
            if name not in KEYWORDS and not name.isdigit():
                ports.add(name)
    #  Header ports written bare - `module m (a, b, c);` with directions below
    bare = re.search(r'\(([^)]*)\)\s*;', header + ');')
    if bare and 'input' not in header and 'output' not in header:
        for name in re.findall(r'\b(\w+)\b', bare.group(1)):
            if name not in KEYWORDS:
                ports.add(name)
    for m in re.finditer(r'\b(?:input|output|inout)\b[^;]*;', body):
        for name in re.findall(r'(\w+)\s*(?:,|;)', m.group(0)):
            if name not in KEYWORDS and not name.isdigit():
                ports.add(name)
    return ports


def declared_names(body, user_types=()):
    """Everything a module declares: ports, wires, regs, logic, parameters, and
    anything declared with a user-defined type.

    The user types matter. red_pitaya_top declares

        SBA_T [MNA-1:0] adc_dat;

    and a checker that only knows the built-in keywords calls `adc_dat`
    undeclared - which is how this script's first run produced six confident
    reports about correct code.
    """
    names = set(module_ports(body))
    kinds = ['wire', 'reg', 'logic', 'integer', 'genvar', 'parameter', 'localparam']
    kinds += [t for t in user_types]
    for m in re.finditer(
            r'\b(?:' + '|'.join(kinds) + r')\b[^;]*;', body):
        chunk = m.group(0)
        chunk = re.sub(r'\[[^\]]*\]', ' ', chunk)       # drop widths and indices
        chunk = re.sub(r'=[^,;]*', ' ', chunk)          # drop initialisers
        for name in re.findall(r'\b(\w+)\b', chunk):
            if name not in KEYWORDS and not name.isdigit():
                names.add(name)
    return names


def find_user_types(sources):
    """Type names a user has introduced, so declarations using them are seen.

    Two spellings, and this project uses the second:

        typedef logic signed [13:0] SBA_T;
        localparam type SBA_T = logic signed [14-1:0];   <- red_pitaya_top.sv

    Missing the second is why the first attempt at this script reported
    `adc_dat` as undeclared. A checker that cries wolf is worse than none,
    because it gets ignored - so it is worth being thorough here.
    """
    types = set()
    for text in sources.values():
        for m in re.finditer(r'\btypedef\b[^;]*?(\w+)\s*(?:\[[^\]]*\]\s*)?;', text):
            types.add(m.group(1))
        for m in re.finditer(r'\b(?:localparam|parameter)\s+type\s+(\w+)\s*=', text):
            types.add(m.group(1))
    return types


def instantiations(body):
    """(module, instance, [connected port names], position) for each instance."""
    out = []
    pattern = re.compile(
        r'\b([A-Za-z_]\w*)\s*'                     # module name
        r'(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?'   # optional parameter block
        r'([A-Za-z_]\w*)\s*'                       # instance name
        r'(?:\[[^\]]*\]\s*)?'                      # optional array range
        r'\(')
    for m in pattern.finditer(body):
        mod, inst = m.group(1), m.group(2)
        if mod in KEYWORDS or inst in KEYWORDS:
            continue
        depth, i = 0, m.end() - 1
        while i < len(body):
            if body[i] == '(':
                depth += 1
            elif body[i] == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        conn = body[m.end():i]
        if '.' not in conn:
            continue                     # positional or not an instantiation
        ports = re.findall(r'\.\s*(\w+)\s*\(', conn)
        out.append((mod, inst, ports, body[:m.start()].count('\n') + 1))
    return out


# ---------------------------------------------------------------------------
def main():
    sources = read_sources()
    if not sources:
        sys.exit('No RTL found. Expected project-owned sources under fpga/.')

    user_types = find_user_types(sources)

    modules, decls, files, bodies = {}, {}, {}, {}
    for path, text in sources.items():
        for m in re.finditer(r'\bmodule\s+(\w+)', text):
            name = m.group(1)
            end = text.find('endmodule', m.end())
            body = text[m.start():end if end > 0 else len(text)]
            modules[name] = module_ports(body)
            decls[name] = declared_names(body, user_types)
            files[name] = path
            bodies[name] = body

    # ----------------------------------------------------------------------
    #  Only what THIS build actually uses.
    #
    #  The source tree carries alternate top levels - red_pitaya_top_Z20,
    #  red_pitaya_top_4ADC_test - for boards this project does not target. They
    #  are not synthesised, and reporting their problems as blocking would train
    #  everyone to ignore the output. Walk down from red_pitaya_top instead and
    #  check only what is reachable.
    # ----------------------------------------------------------------------
    TOP = 'red_pitaya_top'
    reachable, queue = set(), [TOP]
    while queue:
        name = queue.pop()
        if name in reachable or name not in bodies:
            continue
        reachable.add(name)
        for mod, _, _, _ in instantiations(bodies[name]):
            if mod in bodies and mod not in reachable:
                queue.append(mod)
    if TOP not in bodies:
        reachable = set(bodies)          # no known top: check everything
    print(' %d of them are reachable from %s - only those are checked'
          % (len(reachable), TOP))

    print('=' * 70)
    print(' Checking %d files, %d modules' % (len(sources), len(modules)))
    print('=' * 70)

    problems, notes = [], []

    for path, text in sources.items():
        rel = os.path.relpath(path, ROOT)
        for m in re.finditer(r'\bmodule\s+(\w+)', text):
            owner = m.group(1)
            if owner not in reachable:
                continue
            end = text.find('endmodule', m.end())
            body = text[m.start():end if end > 0 else len(text)]

            # --- 1 and 2: instantiations -----------------------------------
            for mod, inst, ports, line in instantiations(body):
                if mod not in modules:
                    continue          # library or IP module, not ours to check
                unknown = [p for p in ports if p not in modules[mod]]
                for p in unknown:
                    problems.append(
                        "%s:%d  instance '%s' of '%s' connects '.%s()', which is "
                        "not a port of that module" % (rel, line, inst, mod, p))
                missing = sorted(modules[mod] - set(ports))
                if missing and not unknown:
                    notes.append("%s:%d  instance '%s' leaves %d port(s) "
                                 "unconnected: %s"
                                 % (rel, line, inst, len(missing),
                                    ', '.join(missing[:6]) +
                                    (' ...' if len(missing) > 6 else '')))

            # --- 3: continuous assignments to undeclared names -------------
            for a in re.finditer(r'\bassign\s+([\w]+)\s*(?:\[[^\]]*\])?\s*=', body):
                target = a.group(1)
                if target not in decls.get(owner, set()):
                    line = body[:a.start()].count('\n') + 1
                    problems.append(
                        "%s:%d  module '%s' assigns to '%s', which it never "
                        "declares" % (rel, line, owner, target))

    seen, ordered = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            ordered.append(p)

    if ordered:
        print('')
        print('PROBLEMS - these WILL fail synthesis:')
        for p in ordered:
            print('   ' + p)
    else:
        print('')
        print('No name mismatches found.')

    if notes:
        print('')
        print('For information - unconnected ports (Vivado allows this):')
        for n in notes[:12]:
            print('   ' + n)
        if len(notes) > 12:
            print('   ... and %d more' % (len(notes) - 12))

    print('')
    print('=' * 70)
    print(' %s' % ('FAILED - fix the above before building'
                   if ordered else 'PASSED - names line up'))
    print('=' * 70)
    return 1 if ordered else 0


if __name__ == '__main__':
    sys.exit(main())
