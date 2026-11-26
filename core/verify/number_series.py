"""Number-series verification: fit rule families, require a unique next value.

The answer is accepted only if at least one integer rule family reproduces every
given term and the resulting next values are identical. Different next values
from valid families = ambiguous -> rejected.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .base import VerificationResult


@dataclass
class RuleFit:
    kind: str
    params: dict
    next_value: int
    description: str


def _is_int(x: float) -> bool:
    return abs(x - round(x)) < 1e-9


def _fit_arithmetic(t: list[int]) -> RuleFit | None:
    if len(t) < 3:
        return None
    d = t[1] - t[0]
    if all(t[i] == t[0] + i * d for i in range(len(t))):
        return RuleFit("arithmetic", {"start": t[0], "diff": d}, t[0] + len(t) * d,
                       f"add {d} each time")
    return None


def _fit_geometric(t: list[int]) -> RuleFit | None:
    if len(t) < 3 or t[0] == 0:
        return None
    # integer ratio only
    if t[0] == 0 or t[1] % t[0] != 0:
        return None
    r = t[1] // t[0]
    if r in (0, 1, -1) or not all(t[i] == t[0] * (r ** i) for i in range(len(t))):
        return None
    return RuleFit("geometric", {"start": t[0], "ratio": r}, t[0] * (r ** len(t)),
                   f"multiply by {r} each time")


def _fit_multiply_add(t: list[int]) -> RuleFit | None:
    if len(t) < 4:
        return None
    if t[1] == t[0]:
        return None
    # Solve t[n+1] = r*t[n] + b from the first three terms (integer check).
    denom = t[1] - t[0]
    num = t[2] - t[1]
    if denom == 0:
        return None
    if abs(num) % abs(denom) != 0:
        return None
    r = num // denom
    b = t[1] - r * t[0]
    if not all(t[i + 1] == r * t[i] + b for i in range(len(t) - 1)):
        return None
    return RuleFit("multiply_add", {"ratio": r, "add": b},
                   t[-1] * r + b, f"multiply by {r} and add {b}")


def _fit_quadratic(t: list[int]) -> RuleFit | None:
    if len(t) < 4:
        return None
    d1 = [t[i + 1] - t[i] for i in range(len(t) - 1)]
    d2 = [d1[i + 1] - d1[i] for i in range(len(d1) - 1)]
    if len(set(d2)) != 1:
        return None
    second = d2[0]
    # t[n] = a n^2 + b n + c with 2a = second
    a2 = second
    # n=0: c=t0; n=1: a2/2 + b = t1-t0
    b = (t[1] - t[0]) - a2 / 2
    if not (_is_int(a2 / 2) or _is_int(b)):
        pass
    n = len(t)
    nxt = a2 / 2 * n * n + b * n + t[0]
    if not _is_int(nxt):
        return None
    return RuleFit("quadratic", {"second_diff": second}, int(round(nxt)),
                   f"constant second difference {second}")


def _fit_fibonacci(t: list[int]) -> RuleFit | None:
    if len(t) < 4:
        return None
    if all(t[i] == t[i - 1] + t[i - 2] for i in range(2, len(t))):
        return RuleFit("fibonacci", {}, t[-1] + t[-2], "each term is the sum of the previous two")
    return None


def _fit_alternate_arithmetic(t: list[int]) -> RuleFit | None:
    if len(t) < 6:
        return None
    evens, odds = t[0::2], t[1::2]
    if len(evens) < 3 or len(odds) < 3:
        return None
    de = evens[1] - evens[0]
    do = odds[1] - odds[0]
    if de == do:
        return None
    if not all(evens[i] == evens[0] + i * de for i in range(len(evens))):
        return None
    if not all(odds[i] == odds[0] + i * do for i in range(len(odds))):
        return None
    if len(t) % 2 == 0:  # next is at an even index in the odd list
        nxt = odds[-1] + do
    else:
        nxt = evens[-1] + de
    return RuleFit("alternate_arithmetic", {"even_diff": de, "odd_diff": do}, nxt,
                   f"two interleaved sequences: +{de} and +{do}")


FITTERS = [_fit_arithmetic, _fit_geometric, _fit_multiply_add, _fit_quadratic,
           _fit_fibonacci, _fit_alternate_arithmetic]


def fit_rules(terms: list[int]) -> list[RuleFit]:
    fits = []
    for fn in FITTERS:
        try:
            fit = fn(terms)
        except (ZeroDivisionError, OverflowError):
            fit = None
        if fit is not None and fit.next_value not in [f.next_value for f in fits]:
            fits.append(fit)
    return fits


def check_stated_rule(terms: list[int], rule: dict | None) -> tuple[bool, str]:
    """Check a stated structured rule reproduces all terms. rule = {type, params}."""
    if not rule:
        return True, "no stated rule"
    kind = str(rule.get("type") or rule.get("kind") or "").lower()
    params = rule.get("params") or rule
    if kind in ("arithmetic", "add", "linear"):
        d = params.get("diff", params.get("d"))
        try:
            d = int(d)
        except (TypeError, ValueError):
            return False, "arithmetic rule missing integer diff"
        if not all(terms[i] == terms[0] + i * d for i in range(len(terms))):
            return False, f"stated rule 'add {d}' does not reproduce the terms"
        return True, ""
    if kind in ("geometric", "multiply", "ratio"):
        r = params.get("ratio", params.get("r"))
        try:
            r = int(r)
        except (TypeError, ValueError):
            return False, "geometric rule missing integer ratio"
        if r in (0, 1) or not all(terms[i] == terms[0] * (r ** i) for i in range(len(terms))):
            return False, f"stated rule 'multiply by {r}' does not reproduce the terms"
        return True, ""
    if kind in ("multiply_add", "affine"):
        r = params.get("ratio", params.get("r"))
        b = params.get("add", params.get("b"))
        try:
            r, b = int(r), int(b)
        except (TypeError, ValueError):
            return False, "multiply_add rule needs integer ratio and add"
        if not all(terms[i + 1] == r * terms[i] + b for i in range(len(terms) - 1)):
            return False, f"stated rule '{r}x+{b}' does not reproduce the terms"
        return True, ""
    if kind in ("fibonacci", "sum"):
        if not all(terms[i] == terms[i - 1] + terms[i - 2] for i in range(2, len(terms))):
            return False, "stated rule 'sum of previous two' does not reproduce the terms"
        return True, ""
    # Unknown textual rule: don't claim it is wrong, just don't rely on it.
    return True, f"stated rule type {kind!r} not machine-checkable"


def verify_number_series(terms, answer, stated_rule: dict | None = None,
                         min_terms: int = 4) -> VerificationResult:
    if not isinstance(terms, (list, tuple)):
        return VerificationResult.failure("terms must be a list", verified=False)
    try:
        terms = [int(t) for t in terms]
    except (TypeError, ValueError):
        return VerificationResult.failure("terms must be integers", verified=False)
    if len(terms) < min_terms:
        return VerificationResult(False, True,
                                  f"underdetermined: only {len(terms)} terms (need {min_terms})",
                                  ambiguity=True, details={"terms": terms})
    try:
        answer_i = int(answer)
    except (TypeError, ValueError):
        return VerificationResult.failure(f"answer {answer!r} is not an integer")
    ok_rule, rule_reason = check_stated_rule(terms, stated_rule)
    if not ok_rule:
        return VerificationResult.failure(rule_reason)
    fits = fit_rules(terms)
    if not fits:
        return VerificationResult.failure("no supported integer rule reproduces all terms",
                                          fits=[])
    predictions = sorted({f.next_value for f in fits})
    details = {"fits": [{"kind": f.kind, "params": f.params, "next": f.next_value,
                         "description": f.description} for f in fits],
               "predictions": predictions}
    if len(predictions) > 1:
        return VerificationResult(False, True,
                                  f"ambiguous: valid rules give different answers {predictions}",
                                  ambiguity=True, details=details)
    expected = predictions[0]
    if answer_i != expected:
        return VerificationResult.failure(
            f"wrong answer: expected {expected}, got {answer_i}", fits=details["fits"])
    return VerificationResult.success(expected,
                                     f"unique solution {expected} via {fits[0].description}",
                                     fits=details["fits"])
