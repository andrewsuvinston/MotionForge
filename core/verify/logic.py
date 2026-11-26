"""Truth-and-lies logic verification: brute-force every truth assignment."""
from __future__ import annotations

from itertools import product

from .base import VerificationResult


def _claim_truth(claim: dict, assignment: dict) -> bool:
    ctype = str(claim.get("type", "")).lower()
    if ctype == "is_liar":
        return assignment[claim["target"]] == 1
    if ctype == "is_truth":
        return assignment[claim["target"]] == 0
    if ctype == "count_liars":
        return sum(assignment.values()) == int(claim["n"])
    if ctype == "count_truth":
        return sum(1 for v in assignment.values() if v == 0) == int(claim["n"])
    raise ValueError(f"unknown claim type {ctype!r}")


def verify_truth_lies(puzzle: dict) -> VerificationResult:
    """puzzle: {people: [names], statements: [{speaker, claim}], answer: [liar names]}.

    Semantics: truth-tellers' claims are true, liars' claims are false.
    """
    people = list(puzzle.get("people") or [])
    statements = list(puzzle.get("statements") or [])
    if len(people) < 2 or not statements:
        return VerificationResult.failure("logic puzzle needs people and statements", verified=False)
    if len(people) > 8:
        return VerificationResult.failure("too many people (max 8)")
    for st in statements:
        if st.get("speaker") not in people:
            return VerificationResult.failure(f"statement speaker {st.get('speaker')!r} unknown")
        claim = st.get("claim") or {}
        if claim.get("type") in ("is_liar", "is_truth") and claim.get("target") not in people:
            return VerificationResult.failure(f"claim target {claim.get('target')!r} unknown")

    solutions = []
    for bits in product([0, 1], repeat=len(people)):
        assignment = dict(zip(people, bits))
        try:
            consistent = all(
                (assignment[st["speaker"]] == 0) == _claim_truth(st["claim"], assignment)
                for st in statements
            )
        except (KeyError, ValueError):
            consistent = False
        if consistent:
            solutions.append(assignment)

    if not solutions:
        return VerificationResult.failure("no consistent assignment — puzzle is contradictory")
    if len(solutions) > 1:
        return VerificationResult(False, True,
                                  f"ambiguous: {len(solutions)} assignments satisfy the statements",
                                  ambiguity=True,
                                  details={"solutions": solutions})
    assignment = solutions[0]
    liars = [p for p in people if assignment[p] == 1]
    stated = puzzle.get("answer")
    if isinstance(stated, list):
        stated_set = {str(x).strip().upper() for x in stated}
        actual_set = {str(x).strip().upper() for x in liars}
        if stated_set != actual_set:
            return VerificationResult.failure(
                f"wrong answer: liars are {liars}, got {stated}")
    elif isinstance(stated, str):
        norm = lambda s: {x.strip().upper() for x in s.replace("and", ",").split(",") if x.strip()}
        if norm(stated) != {p.upper() for p in liars}:
            return VerificationResult.failure(f"wrong answer: liars are {liars}, got {stated}")
    return VerificationResult.success(liars, f"unique solution; liars: {liars}",
                                     solutions=solutions)
