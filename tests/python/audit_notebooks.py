# -*- coding: utf-8 -*-
"""Static audit: walk the notebook's code cells in order, statement by
statement, and flag any name read at module level before anything binds it.

This catches the ordering bugs that runtime testing misses, because a name left
over in a live kernel from a previous run looks defined when it is not.

Function and class bodies are deferred - a helper may legitimately refer to
something a later cell defines - so only module-level reads are checked.
"""
import ast, json, io, sys, builtins

import os as _os
NB = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), '..', '..',
    'notebooks', 'acquisition', 'resonator_coil_characterisation.ipynb'))


def bindings(node):
    """Every name this statement binds at module level."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                out.add(a.asname or a.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name if isinstance(n.name, str) else n.name.id)
    return out


class Loads(ast.NodeVisitor):
    """Module-level name reads, with comprehension and lambda targets excluded."""

    def __init__(self):
        self.found = []
        self.scoped = [set()]

    def _bound(self, name):
        return any(name in s for s in self.scoped)

    # deferred scopes - not checked here
    def visit_FunctionDef(self, n):
        pass

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, n):
        pass

    def visit_Lambda(self, n):
        pass

    def _comp(self, n):
        self.scoped.append(set())
        for gen in n.generators:
            self.visit(gen.iter)
            self.scoped[-1] |= {x.id for x in ast.walk(gen.target)
                                if isinstance(x, ast.Name)}
            for cond in gen.ifs:
                self.visit(cond)
        for attr in ('elt', 'key', 'value'):
            if hasattr(n, attr) and getattr(n, attr) is not None:
                self.visit(getattr(n, attr))
        self.scoped.pop()

    visit_ListComp = _comp
    visit_SetComp = _comp
    visit_GeneratorExp = _comp
    visit_DictComp = _comp

    def visit_Name(self, n):
        if isinstance(n.ctx, ast.Store):
            self.scoped[-1].add(n.id)
        elif isinstance(n.ctx, ast.Load) and not self._bound(n.id):
            self.found.append((n.id, n.lineno))


def audit(path=NB, verbose=True):
    nb = json.load(io.open(path, encoding='utf-8'))
    cells = [(i, ''.join(c['source'])) for i, c in enumerate(nb['cells'])
             if c['cell_type'] == 'code']

    known = set(dir(builtins)) | {'get_ipython', '__name__', '__file__'}
    problems = []

    for idx, text in cells:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            problems.append('cell %d: SYNTAX ERROR %s' % (idx, exc))
            continue
        for stmt in tree.body:
            # a loop or a try binds its own targets before its body runs
            pre = bindings(stmt) if isinstance(
                stmt, (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.If,
                       ast.With, ast.AsyncWith)) else set()
            ld = Loads(); ld.scoped[0] |= pre; ld.visit(stmt)
            for name, line in ld.found:
                if name not in known:
                    problems.append(
                        'cell %d line %d: %r read before anything binds it'
                        % (idx, line, name))
            known |= bindings(stmt)

    if verbose:
        print('audited %d code cells' % len(cells))
        for p in problems:
            print('  ' + p)
        print('PASS - no name is read before it exists' if not problems
              else 'FAIL - %d ordering problem(s)' % len(problems))
    return problems


if __name__ == '__main__':
    sys.exit(1 if audit() else 0)
