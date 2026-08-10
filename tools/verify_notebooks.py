#!/usr/bin/env python3
"""
Check the notebooks for things that cannot possibly work, without running them.

    python3 tools/verify_notebooks.py notebooks/acquisition/*.ipynb

WHY THIS EXISTS
---------------
A notebook has no compiler and no import step. Nothing checks that a call
matches the function it calls, or that a name exists before it is used. The
failure surfaces on the board, minutes into a test, at the one moment it is
needed. Two real examples from 2026-07-29, both of which this now catches in
about a second:

    measure(f, 6, True, settle=0.02, n=250, gap=0)
      TypeError: measure() got an unexpected keyword argument 'gap'
      - an edit gave a caller the use of a new argument, but a faulty guard
        skipped the half that was supposed to add it to the function.

    F_TRUE = require_signal(F_SIG, DEC)
      NameError: name 'F_SIG' is not defined
      - a cell was rewritten wholesale and took the setup block with it.

Both were invisible on the page. Both cost a run on the board.

WHAT IT CHECKS
--------------
  1. CALLS against the functions defined in the same notebook:
     too many positional arguments, an unknown keyword, too few arguments, and
     a return value unpacked into the wrong number of names.

  2. NAMES, in the order the cells actually run:
     every name used at the top level of a cell must already exist by then, and
     every name a function reaches outside itself for must exist somewhere in
     the notebook.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It never executes anything, so it cannot know whether the board is attached or
what a measurement returns. It is a spell-checker, not a test. Passing here
means the notebook is internally consistent, nothing more - but every failure
it reports is certain, not a guess.

Exit status is 0 if everything passes and 1 otherwise, so it can be used in a
script or a build step.
"""

import ast
import builtins
import json
import sys

#  get_ipython is injected by the IPython kernel, so it exists at run time in
#  every notebook and in none of them at read time. Without it here, any
#  notebook that switches its matplotlib backend depending on whether it is
#  under Jupyter - which is the correct way to write one - is reported as
#  broken, and a checker that cries wolf stops being read.
BUILTIN = set(dir(builtins)) | {'__name__', '__file__', '__doc__', 'get_ipython'}


# ---------------------------------------------------------------------------
#  Gathering names
# ---------------------------------------------------------------------------
def _bound_by(node):
    """Every name this statement BINDS - creates or rebinds."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split('.')[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
    return out


def _loaded_by(node):
    """Every name this reads."""
    return {n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _free_names(fn):
    """Names a function reaches OUTSIDE itself for.

    Anything it declares, is passed, assigns to, imports, catches or loops over
    is its own business. What is left has to come from the notebook around it.
    """
    local = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.arg):
            local.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            local.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not fn:
            local.add(n.name)
        elif isinstance(n, ast.alias):
            local.add((n.asname or n.name).split('.')[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            local.add(n.name)
    return _loaded_by(fn) - local - BUILTIN


# ---------------------------------------------------------------------------

def _own_returns(fn):
    """The return statements belonging to THIS function.

    ast.walk descends into nested definitions, so a helper defined inside a
    function would have its returns attributed to the parent - and a parent
    returning a 4-tuple through a 2-tuple-returning inner helper then reads as
    "returns 2". Nested functions are a different function's business.
    """
    out, stack = [], list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out

def check(path):
    nb = json.load(open(path, encoding='utf-8'))
    cells = [''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code']

    problems, trees = [], []
    for k, src in enumerate(cells):
        try:
            trees.append((k, ast.parse(src)))
        except SyntaxError as e:
            problems.append('cell %d: syntax error on line %s - %s' % (k, e.lineno, e.msg))
    if problems:
        return problems

    whole = ast.parse('\n'.join(cells))

    # ---- what the notebook defines ----------------------------------------
    sigs, rets = {}, {}
    for n in ast.walk(whole):
        if isinstance(n, ast.FunctionDef):
            a = n.args
            names = [x.arg for x in a.args]
            sigs[n.name] = (names, len(names) - len(a.defaults),
                            a.vararg is not None, a.kwarg is not None)
            for r in _own_returns(n):
                if isinstance(r.value, ast.Tuple):
                    rets.setdefault(n.name, set()).add(len(r.value.elts))

    # ---- 1. calls ---------------------------------------------------------
    for n in ast.walk(whole):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in sigs:
            names, nreq, va, kw = sigs[n.func.id]
            npos = len(n.args)
            kws = [k.arg for k in n.keywords if k.arg]
            star = any(k.arg is None for k in n.keywords)
            if not va and npos > len(names):
                problems.append("%s(): given %d positional arguments, takes %d"
                                % (n.func.id, npos, len(names)))
            for k in kws:
                if k not in names and not kw:
                    problems.append("%s(): has no argument called '%s'" % (n.func.id, k))
            if not star and npos + len(kws) < nreq:
                problems.append("%s(): given %d arguments, needs %d"
                                % (n.func.id, npos + len(kws), nreq))

    for n in ast.walk(whole):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                and isinstance(n.value.func, ast.Name) and n.value.func.id in rets:
            sizes = rets[n.value.func.id]
            for t in n.targets:
                if isinstance(t, (ast.Tuple, ast.List)) and len(t.elts) not in sizes:
                    problems.append("%s(): unpacked into %d names, returns %s"
                                    % (n.value.func.id, len(t.elts),
                                       ' or '.join(str(s) for s in sorted(sizes))))

    # ---- 2. names, cell by cell, in order ---------------------------------
    #  A function may legitimately use a name a later cell creates, as long as
    #  it is not CALLED before then - so function bodies are checked against
    #  everything the notebook ever defines, and top-level code against only
    #  what exists by the time that cell runs.
    eventual = set()
    for n in ast.walk(whole):
        if isinstance(n, ast.Global):
            eventual |= set(n.names)
    for stmt in whole.body:
        eventual |= _bound_by(stmt)
    eventual |= set(sigs)

    known = set(BUILTIN)
    for k, tree in trees:
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for nm in sorted(_free_names(stmt) - eventual):
                    problems.append("cell %d: %s() uses '%s', which the notebook "
                                    "never defines" % (k, stmt.name, nm))
                known.add(stmt.name)
                continue
            for nm in sorted(_loaded_by(stmt) - _bound_by(stmt) - known):
                problems.append("cell %d: '%s' is used before anything defines it"
                                % (k, nm))
            known |= _bound_by(stmt)

    seen, ordered = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bad = False
    for path in sys.argv[1:]:
        found = check(path)
        print(('FAIL  ' if found else 'ok    ') + path)
        for f in found:
            print('          ' + f)
        bad = bad or bool(found)
    print('')
    print('Some notebooks have problems.' if bad else 'All notebooks consistent.')
    sys.exit(1 if bad else 0)
