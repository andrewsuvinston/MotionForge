"""Karaoke captions: word timings (estimated or from audio) + deterministic HTML/JS."""
from __future__ import annotations

import html
import re


def split_words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def estimate_word_timings(words: list[str], start: float, end: float) -> list[dict]:
    """Distribute words across [start, end] weighted by word length."""
    if not words:
        return []
    if end <= start:
        end = start + 0.5
    weights = [max(1, len(re.sub(r"[^A-Za-z0-9]", "", w)) + 2) for w in words]
    total = sum(weights)
    t = start
    out = []
    for w, weight in zip(words, weights):
        dur = (end - start) * weight / total
        out.append({"text": w, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur
    return out


def captions_for_scene(narration: str, duration: float,
                       word_timings: list[dict] | None = None) -> list[dict]:
    words = split_words(narration)
    if word_timings:
        # Trust explicit timings but clamp inside the scene.
        return [{"text": w["text"], "start": max(0.0, float(w["start"])),
                 "end": min(duration, max(float(w["start"]) + 0.05, float(w["end"])))}
                for w in word_timings]
    start = 0.12 if duration > 1.2 else 0.05
    end = max(start + 0.3, duration - 0.12)
    return estimate_word_timings(words, start, end)


def caption_html(captions: list[dict], max_words: int = 40) -> str:
    spans = []
    for c in captions[:max_words]:
        text = html.escape(c["text"])
        spans.append(f'<span class="word" data-s="{c["start"]:.2f}" data-e="{c["end"]:.2f}">{text}</span>')
    return " ".join(spans)


CAPTION_JS = """
  var cwords = document.querySelectorAll('.word');
  var chunkSize = 6;
  var activeIdx = -1, lastSeen = 0;
  for (var i = 0; i < cwords.length; i++) {
    var s0 = parseFloat(cwords[i].dataset.s), e0 = parseFloat(cwords[i].dataset.e);
    if (t >= s0 && t < e0) { activeIdx = i; }
    if (t >= s0) { lastSeen = i; }
  }
  if (activeIdx < 0) { activeIdx = (t < parseFloat(cwords[0] ? (cwords[0].dataset.s || 0) : 0)) ? 0 : lastSeen; }
  var chunkStart = Math.floor(activeIdx / chunkSize) * chunkSize;
  var chunkEnd = chunkStart + chunkSize;
  for (var i = 0; i < cwords.length; i++) {
    var w = cwords[i], s = parseFloat(w.dataset.s), e = parseFloat(w.dataset.e);
    var cls = 'word';
    if (t >= s && t < e) cls += ' active';
    else if (t >= e) cls += ' past';
    w.className = cls;
    w.style.display = (i >= chunkStart && i < chunkEnd) ? 'inline-block' : 'none';
  }
"""
