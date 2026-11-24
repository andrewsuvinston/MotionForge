"""OpenRouter LLM client: retries with backoff, auto-fallback, JSON extraction.

Every prompt/response pair is saved to <run_dir>/llm_logs/ for debugging.
"""
from __future__ import annotations

import difflib
import json
import logging
import random
import re
import time
from pathlib import Path

import httpx

log = logging.getLogger("motionforge.llm")

# Errors where retrying the same model is pointless -> switch to fallback now.
IMMEDIATE_FALLBACK_STATUS = {400, 401, 402, 403, 404, 422}
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    pass


def extract_json(text: str):
    """Robustly pull a JSON object/array out of an LLM reply."""
    if not text:
        raise ValueError("empty response")
    text = text.strip()
    # Strip markdown code fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Scan for the first balanced {...} or [...] block.
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
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    raise ValueError("no valid JSON found in response")


class LLMClient:
    def __init__(self, cfg: dict, log_dir: Path | None = None):
        self.cfg = cfg
        self.api_key = cfg.get("api_key", "")
        self.base_url = cfg["llm"]["base_url"].rstrip("/")
        self.max_retries = int(cfg["llm"]["max_retries"])
        self.timeout = float(cfg["llm"]["timeout_seconds"])
        self.fallback_model = cfg["models"]["fallback_model"]
        self.free_model = cfg["models"].get("free_model") or ""
        self.log_dir = Path(log_dir) if log_dir else None
        self._log_counter = 0
        self._model_ids: list[str] | None = None
        self._resolve_cache: dict[str, str] = {}
        self._client = httpx.Client(timeout=self.timeout)
        self.offline = not self.api_key

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
        """Map a configured id to a real OpenRouter id (strip bad suffixes, fuzzy match)."""
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

    def _save_log(self, label: str, payload: dict, response: str | None, model: str, error: str | None = None):
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._log_counter += 1
        # Truncate base64 image blobs so logs stay readable.
        def _trim(obj):
            if isinstance(obj, dict):
                return {k: _trim(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_trim(v) for v in obj]
            if isinstance(obj, str) and len(obj) > 20000:
                return obj[:2000] + f"...[truncated {len(obj)} chars]"
            return obj
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "label": label,
            "model": model,
            "request": _trim(payload),
            "response": response,
            "error": error,
        }
        path = self.log_dir / f"{self._log_counter:03d}_{re.sub(r'[^a-z0-9_]+', '_', label.lower())}.json"
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------------- core call ----------------

    def _attempt(self, model: str, payload: dict, label: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/motionforge",
            "X-Title": "MotionForge",
        }
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self._client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                if r.status_code == 402:
                    # Credit limit: adapt max_tokens to what the account can afford.
                    body = r.text[:600]
                    m = re.search(r"can only afford (\d+)", body)
                    if m:
                        affordable = int(m.group(1)) - 64
                        if affordable >= 512 and payload.get("max_tokens", 0) > affordable:
                            log.warning("402 credit limit: reducing max_tokens %s -> %s for %s",
                                        payload.get("max_tokens"), affordable, model)
                            payload["max_tokens"] = affordable
                            self._save_log(label, payload, None, model, error="402: reducing max_tokens")
                            continue
                    self._save_log(label, payload, None, model, error=f"HTTP 402: {body}")
                    raise LLMError(f"HTTP 402 from {model}: {body}")
                if r.status_code in IMMEDIATE_FALLBACK_STATUS:
                    body = r.text[:500]
                    self._save_log(label, payload, None, model, error=f"HTTP {r.status_code}: {body}")
                    raise LLMError(f"HTTP {r.status_code} from {model}: {body}")
                if r.status_code in RETRY_STATUS or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    raise LLMError(str(data["error"])[:300])
                content = data["choices"][0]["message"]["content"] or ""
                usage = data.get("usage", {})
                self._save_log(label, payload, content, model)
                log.info("LLM %s [%s] ok (%s tokens)", label, model, usage.get("total_tokens", "?"))
                return content
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_err = exc
                wait = min(2 ** attempt + random.uniform(0, 1), 30)
                log.warning("LLM %s attempt %d/%d failed (%s); retrying in %.1fs",
                            label, attempt, self.max_retries, exc, wait)
                self._save_log(label, payload, None, model, error=f"attempt {attempt}: {exc}")
                if attempt < self.max_retries:
                    time.sleep(wait)
        raise LLMError(f"{model} failed after {self.max_retries} attempts: {last_err}")

    def chat(self, messages: list[dict], model: str, label: str = "chat",
             max_tokens: int | None = None, temperature: float | None = None) -> str:
        """Call a model with retries, then auto-fallback. Raises LLMError if all fail."""
        if self.offline:
            raise LLMError("No OPENROUTER_API_KEY configured (offline mode)")
        model = self.resolve_model(model)
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or int(self.cfg["llm"]["max_tokens"]),
            "temperature": self.cfg["llm"]["temperature"] if temperature is None else temperature,
        }
        try:
            return self._attempt(model, payload, label)
        except LLMError as exc:
            fallback = self.resolve_model(self.fallback_model)
            if fallback != model:
                log.warning("Falling back from %s to %s (%s)", model, fallback, exc)
                payload["model"] = fallback
                try:
                    return self._attempt(fallback, payload, label + "_fallback")
                except LLMError as exc2:
                    exc = exc2
            free = self.resolve_model(self.free_model) if self.free_model else ""
            if free and free not in (model, fallback):
                log.warning("Falling back to free model %s (%s)", free, exc)
                payload["model"] = free
                return self._attempt(free, payload, label + "_free")
            raise

    def chat_json(self, messages: list[dict], model: str, label: str = "json",
                  max_tokens: int | None = None, temperature: float | None = None):
        """Chat + robust JSON extraction, with one repair retry on bad JSON."""
        text = self.chat(messages, model, label=label, max_tokens=max_tokens, temperature=temperature)
        try:
            return extract_json(text)
        except ValueError:
            log.warning("Bad JSON from %s (%s); asking for repair", model, label)
            repair = messages + [
                {"role": "assistant", "content": text[:8000]},
                {"role": "user", "content": "Your previous reply was not valid JSON. "
                 "Reply again with ONLY the valid JSON value, no prose, no code fences."},
            ]
            text2 = self.chat(repair, model, label=label + "_repair", max_tokens=max_tokens, temperature=0.1)
            return extract_json(text2)

    def close(self):
        self._client.close()
