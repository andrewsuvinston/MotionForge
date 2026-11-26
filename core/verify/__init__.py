"""Verification registry: dispatch structured puzzles to code verifiers."""
from __future__ import annotations

from .arithmetic import (verify_algebra, verify_arithmetic, verify_percentage,
                         verify_ratio, verify_time_work)
from .base import VerificationResult, normalize_answer
from .crossing import verify_crossing
from .logic import verify_truth_lies
from .number_series import verify_number_series

VERIFIERS = {
    "number_series": lambda p: verify_number_series(
        p.get("terms"), p.get("answer"), p.get("rule")),
    "arithmetic": verify_arithmetic,
    "percentage": verify_percentage,
    "ratio": verify_ratio,
    "time_work": verify_time_work,
    "algebra": verify_algebra,
    "truth_lies": verify_truth_lies,
    "river": verify_crossing,
    "crossing": verify_crossing,
}

SUPPORTED_TYPES = sorted(VERIFIERS)


def verify_puzzle(puzzle: dict) -> VerificationResult:
    """Verify a structured puzzle. Unknown types are returned as unverified."""
    if not isinstance(puzzle, dict):
        return VerificationResult.failure("puzzle is not an object", verified=False)
    ptype = str(puzzle.get("type") or "").lower()
    fn = VERIFIERS.get(ptype)
    if fn is None:
        return VerificationResult.failure(
            f"no code verifier for puzzle type {ptype!r}", verified=False,
            supported=SUPPORTED_TYPES)
    try:
        return fn(puzzle)
    except Exception as exc:  # noqa: BLE001
        return VerificationResult.failure(f"verifier error: {exc}", verified=False)


__all__ = ["VerificationResult", "verify_puzzle", "normalize_answer",
           "SUPPORTED_TYPES", "VERIFIERS"]
