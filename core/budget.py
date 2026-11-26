"""Budget manager: daily request limits, per-run caps, live bar, caching, honest reporting.

The account may be on a free tier with near-zero credits, so every LLM call is
counted, cached when identical, and skipped once the budget is spent. When that
happens the pipeline degrades to deterministic templates and the report says so.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("motionforge.budget")


class BudgetExhausted(RuntimeError):
    pass


class BudgetManager:
    def __init__(self, cfg: dict, root: Path, run_id: str = ""):
        b = cfg.get("budget", {})
        self.daily_limit = int(b.get("daily_request_limit", 50))
        self.run_limit = int(b.get("max_requests_per_run", 24))
        self.max_cost = float(b.get("max_cost_usd", 0.10))
        self.cache_enabled = bool(b.get("cache_enabled", True))
        self.root = Path(root)
        self.path = self.root / "memory" / "budget.json"
        self.cache_dir = self.root / "memory" / "llm_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.today = time.strftime("%Y-%m-%d")
        self.data = self._load()
        self.run_calls = 0
        self.run_cost = 0.0
        self.stage_calls: dict[str, int] = {}
        self.cache_hits = 0
        self.usage_log: list[dict] = []
        self.estimates: dict[str, int] = {}

    # ---------------- persistence ----------------

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("date") == self.today:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {"date": self.today, "requests": 0, "cost": 0.0, "runs": {}}

    def save(self):
        self.data["requests"] = self.data.get("requests", 0)
        self.data["runs"] = self.data.get("runs", {})
        if self.run_id:
            self.data["runs"][self.run_id] = {
                "requests": self.run_calls, "cost": round(self.run_cost, 6),
                "stages": self.stage_calls,
            }
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    # ---------------- quota ----------------

    @property
    def daily_used(self) -> int:
        return int(self.data.get("requests", 0))

    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.daily_used)

    def remaining_run(self) -> int:
        return max(0, self.run_limit - self.run_calls)

    def can_call(self) -> bool:
        return self.remaining_today() > 0 and self.remaining_run() > 0 \
            and self.run_cost < self.max_cost

    def estimate(self, stage: str, calls: int) -> bool:
        """Estimate a stage's calls; warn if the run budget would be exceeded."""
        self.estimates[stage] = calls
        projected = self.run_calls + calls
        if projected > self.run_limit or self.daily_used + calls > self.daily_limit:
            log.warning("Budget: stage %s needs ~%d calls; projected %d/%d for this run, "
                        "%d/%d today — will degrade to deterministic fallbacks",
                        stage, calls, projected, self.run_limit,
                        self.daily_used + calls, self.daily_limit)
            return False
        log.info("Budget: stage %s estimates %d call(s) | %s", stage, calls, self.bar())
        return True

    def record(self, stage: str, model: str, tokens: int = 0, cost: float = 0.0,
               cached: bool = False, ok: bool = True):
        if cached:
            self.cache_hits += 1
            return
        self.run_calls += 1
        self.data["requests"] = self.daily_used + 1
        self.data["cost"] = round(float(self.data.get("cost", 0.0)) + cost, 6)
        self.run_cost += cost
        self.stage_calls[stage] = self.stage_calls.get(stage, 0) + 1
        self.usage_log.append({"stage": stage, "model": model, "tokens": tokens,
                               "cost": round(cost, 6), "ok": ok,
                               "ts": time.strftime("%H:%M:%S")})
        log.info("Budget %s | %s", self.bar(), self._stage_line(stage))
        self.save()

    def _stage_line(self, stage: str) -> str:
        return f"stage={stage} run={self.run_calls}/{self.run_limit} cost=${self.run_cost:.4f}"

    def bar(self) -> str:
        used, total = self.daily_used, max(1, self.daily_limit)
        n = 12
        filled = min(n, round(n * used / total))
        return f"[{'#' * filled}{'-' * (n - filled)}] {used}/{total} today"

    # ---------------- response cache ----------------

    def cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get_cached(self, key: str) -> str | None:
        if not self.cache_enabled:
            return None
        p = self.cache_path(key)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self.cache_hits += 1
                return data.get("response")
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def put_cached(self, key: str, response: str, model: str):
        if not self.cache_enabled:
            return
        try:
            self.cache_path(key).write_text(json.dumps(
                {"model": model, "response": response,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass

    def snapshot(self) -> dict:
        return {
            "daily_limit": self.daily_limit,
            "daily_used": self.daily_used,
            "run_limit": self.run_limit,
            "run_requests": self.run_calls,
            "run_cost_usd": round(self.run_cost, 6),
            "max_cost_usd": self.max_cost,
            "cache_hits": self.cache_hits,
            "stages": self.stage_calls,
            "estimates": self.estimates,
            "calls": self.usage_log,
            "exhausted": not self.can_call(),
        }
