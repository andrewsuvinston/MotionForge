"""OpenRouter LLM client with budget awareness, caching, retries and fallbacks.

Tiers:
  high  -> generator_model -> fallback_model -> free_model   (puzzle/hook/script/fix)
  cheap -> cheap_model    -> fallback_model                  (metadata, judges, formatting)

All prompts/responses are logged; identical prompts are served from cache; failed
models are skipped for the rest of the run; Retry-After is respected.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import random
import re
import time
from pathlib import Path

import httpx

from .budget import BudgetManager

log = logging.getLogger("motionforge.llm")

IMMEDIATE_FALLBACK_STATUS = {400, 401, 402, 403, 404, 422}
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    pass


def extract_json(text: str):
    """Robustly pull a JSON object/array out of an LLM reply."""
    if not text:
        raise ValueError("empty response")
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("no valid JSON found in response")


def _is_vision(messages: list[dict]) -> bool:
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in c):
            return True
    return False


class LLMClient:
    def __init__(self, cfg: dict, log_dir: Path | None = None,
                 budget: BudgetManager | None = None):
        self.cfg = cfg
        self.api_key = cfg.get("api_key", "")
        self.base_url = cfg["llm"]["base_url"].rstrip("/")
        self.max_retries = int(cfg["llm"]["max_retries"])
        self.timeout = float(cfg["llm"]["timeout_seconds"])
        self.fallback_model = cfg["models"]["fallback_model"]
        self.free_model = cfg["models"].get("free_model") or ""
        self.cheap_model = cfg["models"].get("cheap_model") or self.free_model
        self.log_dir = Path(log_dir) if log_dir else None
        self.budget = budget
        self._log_counter = 0
        self._model_ids: list[str] | None = None
        self._resolve_cache: dict[str, str] = {}
        self._client = httpx.Client(timeout=self.timeout)
        self.offline = not self.api_key
        self.dead_models: set[str] = set()
        self.models_used: set[str] = set()
        self.degraded = False
        self.degraded_reasons: list[str] = []

    # ---------------- model resolution ----------------

    def _fetch_model_ids(self) -> list[str]:
        if self._model_ids is None:
            try:
                r = self._client.get(f"{self.base_url}/models", timeout=60)
                r.raise_for_status()
                self._model_ids = [m["id"] for m in r.json().get("data", [])]
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not fetch model list: %s", exc)
                self._model_ids = []
        return self._model_ids

    def resolve_model(self, model: str) -> str:
        if model in self._resolve_cache:
            return self._resolve_cache[model]
        ids = self._fetch_model_ids()
        resolved = model
        if ids and model not in ids:
            base = model.split(":")[0]
            if base in ids:
                resolved = base
            else:
                close = difflib.get_close_matches(base, ids, n=1, cutoff=0.85)
                resolved = close[0] if close else model
            log.warning("Model %r not found; resolved to %r", model, resolved)
        self._resolve_cache[model] = resolved
        return resolved

    # ---------------- logging ----------------

    def _save_log(self, label: str, payload: dict, response: str | None,
                  model: str, error: str | None = None):
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._log_counter += 1

        def _trim(obj):
            if isinstance(obj, dict):
                return {k: _trim(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_trim(v) for v in obj]
            if isinstance(obj, str) and len(obj) > 20000:
                return obj[:2000] + f"...[truncated {len(obj)} chars]"
            return obj

        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label,
                 "model": model, "request": _trim(payload),
                 "response": response, "error": error}
        path = self.log_dir / f"{self._log_counter:03d}_{re.sub(r'[^a-z0-9_]+', '_', label.lower())}.json"
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------------- core call ----------------

    def _attempt(self, model: str, payload: dict, label: str, stage: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/motionforge",
            "X-Title": "MotionForge",
        }
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.budget and not self.budget.can_call():
                    raise LLMError("budget exhausted for this run/day")
                r = self._client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After", "")
                    wait = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 5
                    wait = min(max(wait, 1), 30)
                    self._save_log(label, payload, None, model, error=f"429 retry-after {wait}s")
                    log.warning("429 rate limit from %s; waiting %.1fs", model, wait)
                    time.sleep(wait)
                    raise httpx.HTTPStatusError("429", request=r.request, response=r)
                if r.status_code == 402:
                    body = r.text[:600]
                    m = re.search(r"can only afford (\d+)", body)
                    if m:
                        affordable = int(m.group(1)) - 64
                        if affordable >= 512 and payload.get("max_tokens", 0) > affordable:
                            log.warning("402 credit limit: reducing max_tokens %s -> %s",
                                        payload.get("max_tokens"), affordable)
                            payload["max_tokens"] = affordable
                            self._save_log(label, payload, None, model, error="402: reducing max_tokens")
                            continue
                    self._save_log(label, payload, None, model, error=f"HTTP 402: {body}")
                    self.dead_models.add(model)
                    if self.budget:
                        self.budget.record(stage, model, ok=False)
                    raise LLMError(f"HTTP 402 from {model}: {body}")
                if r.status_code in IMMEDIATE_FALLBACK_STATUS:
                    body = r.text[:500]
                    self._save_log(label, payload, None, model, error=f"HTTP {r.status_code}: {body}")
                    if r.status_code in (401, 403, 404):
                        self.dead_models.add(model)
                    if self.budget:
                        self.budget.record(stage, model, ok=False)
                    raise LLMError(f"HTTP {r.status_code} from {model}: {body}")
                if r.status_code in RETRY_STATUS or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    raise LLMError(str(data["error"])[:300])
                content = data["choices"][0]["message"]["content"] or ""
                usage = data.get("usage", {}) or {}
                tokens = int(usage.get("total_tokens", 0) or 0)
                cost = float(usage.get("cost", 0.0) or 0.0)
                self._save_log(label, payload, content, model)
                self.models_used.add(model)
                if self.budget:
                    self.budget.record(stage, model, tokens=tokens, cost=cost)
                log.info("LLM %s [%s] ok (%s tokens)", label, model, tokens or "?")
                return content
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_err = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None \
                        and exc.response.status_code == 429:
                    if attempt < self.max_retries:
                        continue
                wait = min(2 ** attempt + random.uniform(0, 1), 20)
                log.warning("LLM %s attempt %d/%d failed (%s); retrying in %.1fs",
                            label, attempt, self.max_retries, exc, wait)
                self._save_log(label, payload, None, model, error=f"attempt {attempt}: {exc}")
                if attempt < self.max_retries:
                    time.sleep(wait)
        raise LLMError(f"{model} failed after {self.max_retries} attempts: {last_err}")

    def _chain(self, tier: str) -> list[str]:
        if tier == "cheap":
            names = [self.cheap_model, self.fallback_model]
        else:
            names = [self.cfg["models"]["generator_model"], self.fallback_model, self.free_model]
        out = []
        for name in names:
            if not name:
                continue
            resolved = self.resolve_model(name)
            if resolved and resolved not in out and resolved not in self.dead_models:
                out.append(resolved)
        return out

    def chat(self, messages: list[dict], model: str | None = None, label: str = "chat",
             max_tokens: int | None = None, temperature: float | None = None,
             tier: str = "high", stage: str = "general") -> str:
        """Call with budget/cache/fallbacks. Raises LLMError if every option fails."""
        if self.offline:
            raise LLMError("No OPENROUTER_API_KEY configured (offline mode)")
        if self.budget and not self.budget.can_call():
            raise LLMError("budget exhausted")
        if self.budget:
            self.budget.estimate(stage, 1)

        chain = self._chain(tier)
        if model:
            resolved = self.resolve_model(model)
            if resolved not in self.dead_models:
                chain = [resolved] + [m for m in chain if m != resolved]
        if not chain:
            self.degraded = True
            self.degraded_reasons.append(f"{stage}: no usable models")
            raise LLMError("no usable models (all failed or budget exhausted)")

        max_tok = max_tokens or int(self.cfg["llm"]["max_tokens"])
        temp = self.cfg["llm"]["temperature"] if temperature is None else temperature
        vision = _is_vision(messages)
        cache_key = ""
        if self.budget and not vision:
            raw = json.dumps({"m": messages, "mt": max_tok, "t": temp}, sort_keys=True,
                             ensure_ascii=False)
            cache_key = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
            cached = self.budget.get_cached(cache_key)
            if cached is not None:
                log.info("LLM %s served from cache", label)
                return cached

        last_err: Exception | None = None
        for i, model_id in enumerate(chain):
            payload = {"model": model_id, "messages": messages,
                       "max_tokens": max_tok, "temperature": temp}
            try:
                content = self._attempt(model_id, payload, label, stage)
                if cache_key and self.budget:
                    self.budget.put_cached(cache_key, content, model_id)
                return content
            except LLMError as exc:
                last_err = exc
                log.warning("Model %s failed for %s (%s)", model_id, label, str(exc)[:200])
                continue
        self.degraded = True
        self.degraded_reasons.append(f"{stage}: all models failed ({str(last_err)[:120]})")
        raise LLMError(f"all models failed for {label}: {last_err}")

    def chat_json(self, messages: list[dict], model: str | None = None, label: str = "json",
                  max_tokens: int | None = None, temperature: float | None = None,
                  tier: str = "high", stage: str = "general"):
        text = self.chat(messages, model, label=label, max_tokens=max_tokens,
                         temperature=temperature, tier=tier, stage=stage)
        try:
            return extract_json(text)
        except ValueError:
            log.warning("Bad JSON (%s); requesting repair", label)
            repair = messages + [
                {"role": "assistant", "content": text[:8000]},
                {"role": "user", "content": "Your previous reply was not valid JSON. Reply again "
                 "with ONLY the valid JSON value, no prose, no code fences."},
            ]
            text2 = self.chat(repair, model, label=label + "_repair",
                              max_tokens=max_tokens, temperature=0.1, tier=tier, stage=stage)
            return extract_json(text2)

    def close(self):
        if self.budget:
            self.budget.save()
        self._client.close()
