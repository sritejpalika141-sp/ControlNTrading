"""
Fast pre-commit safety check — runs with ZERO third-party dependencies.

    python3 precommit_check.py          # exit 0 = safe to commit

Why this exists (gaps #1 and #4):
  * py_compile — the only check the deploy previously had — CANNOT catch import errors,
    because the syntax is valid. A module-level `from state import calculate_position_size`
    was added while state.py already did `from fyers_client import FyersClient`; that
    circular import only failed when Python actually imported the module, i.e. at service
    start on the live trading VM. It crash-looped production.
  * TWO agents (a human/Claude and Antigravity) commit to this same branch. smoke_test.py
    catches this class of bug but needs the venv and ~90s, so it is not something every
    commit will run. This check is instant and dependency-free, so it can gate EVERY commit
    from EITHER agent via .git/hooks/pre-commit.

What it does
  1. py_compile every tracked .py file under trading-app/  (syntax)
  2. Build a MODULE-LEVEL import graph by AST and report import CYCLES (the real killer).
     Only module-scope imports are considered — function-local imports are the accepted fix
     for a cycle and must not be flagged.

What it does NOT do
  It does not import anything, so it cannot catch runtime/startup errors. Run smoke_test.py
  before deploying for that.
"""
import ast
import os
import py_compile
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {".venv", "__pycache__", "logs", "data", "node_modules", ".git", "static"}


def local_modules():
    """Map importable module name -> path, for .py files in this project."""
    mods = {}
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, BASE)[:-3].replace(os.sep, ".")
            if rel.endswith(".__init__"):
                rel = rel[: -len(".__init__")]
            mods[rel] = p
    return mods


def module_level_imports(path):
    """Return module names imported at MODULE scope (function-local imports ignored)."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        return set()          # syntax is reported separately by py_compile
    found = set()

    def walk(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue      # function/class-local imports cannot create a startup cycle
            if isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    found.add(node.module)
            # module-level control flow still executes at import time
            for attr in ("body", "orelse", "finalbody"):
                inner = getattr(node, attr, None)
                if isinstance(inner, list):
                    walk(inner)
            for h in getattr(node, "handlers", []) or []:
                walk(h.body)

    walk(tree.body)
    return found


def find_cycles(graph):
    """Return simple cycles in the import graph (DFS with an explicit stack)."""
    cycles, seen = [], set()

    def dfs(node, stack, visiting):
        for nxt in graph.get(node, ()):
            if nxt in visiting:
                cyc = stack[stack.index(nxt):] + [nxt]
                key = tuple(sorted(set(cyc)))
                if key not in seen:
                    seen.add(key)
                    cycles.append(cyc)
                continue
            visiting.add(nxt)
            dfs(nxt, stack + [nxt], visiting)
            visiting.discard(nxt)

    for n in list(graph):
        dfs(n, [n], {n})
    return cycles


def main():
    mods = local_modules()
    ok = True

    print("pre-commit check\n")

    # 1. syntax
    bad = []
    for name, path in sorted(mods.items()):
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as e:
            bad.append((name, str(e).strip().splitlines()[-1]))
    if bad:
        ok = False
        print(f"  ❌ syntax errors in {len(bad)} file(s):")
        for n, err in bad:
            print(f"     {n}: {err}")
    else:
        print(f"  ✅ syntax OK ({len(mods)} files)")

    # 2. module-level import cycles
    graph = {}
    for name, path in mods.items():
        deps = {m for m in module_level_imports(path) if m in mods and m != name}
        graph[name] = deps
    cycles = find_cycles(graph)
    if cycles:
        ok = False
        print(f"\n  ❌ MODULE-LEVEL IMPORT CYCLE(S) — these crash the app at startup:")
        for c in cycles:
            print("     " + " -> ".join(c))
        print("\n     Fix: move one of the imports INSIDE the function that uses it")
        print("     (a function-local import does not run at module import time).")
    else:
        print("  ✅ no module-level import cycles")

    print("\n" + "=" * 58)
    if ok:
        print("RESULT: PASS — safe to commit.")
        print("Before DEPLOYING, also run:  .venv/bin/python3 smoke_test.py")
        return 0
    print("RESULT: FAIL — do not commit; this would break the live app.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
