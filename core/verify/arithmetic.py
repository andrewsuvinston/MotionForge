"""Arithmetic / algebra / percentage / ratio / time-and-work verification (sympy)."""
from __future__ import annotations

import re

import sympy as sp

from .base import VerificationResult

FORBIDDEN = ("__", "import", "lambda", "exec", "eval", ";", "=")


def _safe_expr(text: str):
    s = str(text or "").strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not s or any(f in s.lower() for f in FORBIDDEN):
        raise ValueError(f"unsafe expression: {text!r}")
    if not re.fullmatch(r"[0-9xX+\-*/().\s^]+", s):
        raise ValueError(f"unsupported characters in expression: {text!r}")
    return sp.sympify(s, evaluate=True)


def verify_arithmetic(puzzle: dict) -> VerificationResult:
    expression = puzzle.get("expression")
    try:
        expected = float(sp.N(_safe_expr(expression)))
    except Exception as exc:  # noqa: BLE001
        return VerificationResult.failure(f"cannot evaluate expression: {exc}")
    try:
        given = float(puzzle.get("answer"))
    except (TypeError, ValueError):
        return VerificationResult.failure("answer missing or not numeric")
    if abs(expected - given) > 1e-6:
        return VerificationResult.failure(f"wrong answer: expression = {expected:g}, got {given:g}")
    return VerificationResult.success(expected, f"expression evaluates to {expected:g}")


def verify_percentage(puzzle: dict) -> VerificationResult:
    try:
        base = float(puzzle["base"])
        pct = float(puzzle["percent"])
        given = float(puzzle.get("answer"))
    except (KeyError, TypeError, ValueError):
        return VerificationResult.failure("percentage puzzle needs base, percent, answer")
    expected = base * pct / 100.0
    if abs(expected - given) > 1e-6:
        return VerificationResult.failure(f"wrong answer: {pct:g}% of {base:g} = {expected:g}, got {given:g}")
    return VerificationResult.success(expected)


def verify_ratio(puzzle: dict) -> VerificationResult:
    try:
        ratio = [float(x) for x in puzzle["ratio"]]
        total = float(puzzle["total"])
        given = [float(x) for x in puzzle.get("answer", [])]
    except (KeyError, TypeError, ValueError):
        return VerificationResult.failure("ratio puzzle needs ratio, total, answer list")
    if len(ratio) < 2 or len(given) != len(ratio) or sum(ratio) <= 0:
        return VerificationResult.failure("invalid ratio structure")
    if abs(sum(given) - total) > 1e-6:
        return VerificationResult.failure(f"parts sum to {sum(given):g}, expected {total:g}")
    expected = [total * r / sum(ratio) for r in ratio]
    if any(abs(a - b) > 1e-6 for a, b in zip(expected, given)):
        return VerificationResult.failure(f"wrong split: expected {expected}, got {given}")
    return VerificationResult.success(given)


def verify_time_work(puzzle: dict) -> VerificationResult:
    try:
        times = [float(x) for x in puzzle["times"]]
        given = float(puzzle.get("answer_days", puzzle.get("answer")))
    except (KeyError, TypeError, ValueError):
        return VerificationResult.failure("time_work puzzle needs times and answer_days")
    if not times or any(t <= 0 for t in times):
        return VerificationResult.failure("times must be positive")
    expected = 1.0 / sum(1.0 / t for t in times)
    if abs(expected - given) > 0.01:
        return VerificationResult.failure(f"wrong answer: combined rate gives {expected:.4f}, got {given}")
    return VerificationResult.success(round(expected, 4))


def verify_algebra(puzzle: dict) -> VerificationResult:
    equation = str(puzzle.get("equation") or "")
    if "=" not in equation or any(f in equation.lower() for f in ("__", "import", "lambda", "exec", "eval", ";")):
        return VerificationResult.failure("algebra puzzle needs an equation like 2*x+3=11")
    try:
        left, right = equation.split("=", 1)
        x = sp.Symbol("x")
        sol = sp.solve(sp.Eq(_safe_expr(left), _safe_expr(right)), x)
    except Exception as exc:  # noqa: BLE001
        return VerificationResult.failure(f"cannot solve equation: {exc}")
    if len(sol) != 1:
        return VerificationResult.failure(f"equation has {len(sol)} solutions (need exactly one)")
    expected = float(sol[0])
    try:
        given = float(puzzle.get("answer"))
    except (TypeError, ValueError):
        return VerificationResult.failure("answer missing or not numeric")
    if abs(expected - given) > 1e-6:
        return VerificationResult.failure(f"wrong answer: x = {expected:g}, got {given:g}")
    return VerificationResult.success(expected)
