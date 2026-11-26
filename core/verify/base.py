"""Puzzle verification result types."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class VerificationResult:
    ok: bool
    verified: bool                    # True = checked by deterministic code
    reason: str
    answer: object = None
    ambiguity: bool = False
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def failure(cls, reason: str, verified: bool = True, **details) -> "VerificationResult":
        return cls(False, verified, reason, details=details)

    @classmethod
    def success(cls, answer, reason: str = "verified", **details) -> "VerificationResult":
        return cls(True, True, reason, answer=answer, details=details)


def normalize_answer(value) -> str:
    """Normalize answers for cross-checking (LLM vs code vs blind solve)."""
    import json
    import re
    if isinstance(value, (int, float)):
        f = float(value)
        return str(int(f)) if f == int(f) else f"{f:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return ",".join(normalize_answer(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    s = str(value or "").strip().lower()
    s = re.sub(r"^(the\s+)?answer\s*(is|:|=)\s*", "", s)
    s = s.strip(" .!?\"'")
    try:
        return normalize_answer(float(s))
    except ValueError:
        return s
