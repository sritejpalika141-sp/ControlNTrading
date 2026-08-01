"""AST gate: record_trade() must nest inside async with state.order_lock in place_order."""
from __future__ import annotations

import ast
from pathlib import Path


APP_PY = Path(__file__).resolve().parents[1] / "app.py"


def _find_place_order_fn(tree: ast.AST) -> ast.AsyncFunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "place_order":
            return node
        # Also search nested (unlikely) / Module body only is enough for FastAPI handlers
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "place_order":
            # Prefer the /api/order handler — first match named place_order at module level
            return node
    return None


def _lock_with_contains_record_trade(fn: ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.AsyncWith):
            continue
        # Look for `async with state.order_lock`
        locked = False
        for item in node.items:
            ctx = item.context_expr
            if (
                isinstance(ctx, ast.Attribute)
                and ctx.attr == "order_lock"
                and isinstance(ctx.value, ast.Name)
                and ctx.value.id == "state"
            ):
                locked = True
                break
        if not locked:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Attribute) and func.attr == "record_trade":
                    return True
                if isinstance(func, ast.Name) and func.id == "record_trade":
                    return True
    return False


def test_place_order_record_trade_inside_order_lock():
    src = APP_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Find the HTTP place_order that uses order_lock (API order path)
    candidates = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "place_order"
    ]
    assert candidates, "place_order async function not found in app.py"
    assert any(_lock_with_contains_record_trade(fn) for fn in candidates), (
        "record_trade() must be nested inside `async with state.order_lock` in place_order"
    )
