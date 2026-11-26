"""Automatic quality checks for mobile-first Shorts scenes.

The DOM measurement script (MEASURE_JS) runs inside Playwright; all check logic
is pure Python so it can be unit-tested with synthetic measurements.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# Collects every element that has its own visible text (for typography checks)
# plus every visual block marked .occ (for occupancy / safe-area checks).
MEASURE_JS = r"""
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const all = Array.from(document.body.querySelectorAll('*'));
  const textEls = all.filter(el =>
    Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim()));
  const idx = new Map(textEls.map((el, i) => [el, i]));
  function effOpacity(el) {
    let o = 1, n = el;
    while (n && n.nodeType === 1) {
      const s = getComputedStyle(n);
      if (s.visibility === 'hidden' || s.display === 'none') return 0;
      o *= parseFloat(s.opacity);
      n = n.parentElement;
    }
    return o;
  }
  function effBg(el) {
    // Composite translucent background layers down to an opaque approximation so
    // contrast math never compares text against a see-through surface.
    let layers = [];
    let n = el;
    while (n && n.nodeType === 1) {
      const c = getComputedStyle(n).backgroundColor;
      const m = c && c.match(/[\d.]+/g);
      if (m) {
        const a = m.length < 4 ? 1 : parseFloat(m[3]);
        if (a > 0.01) layers.push({r: +m[0], g: +m[1], b: +m[2], a});
        if (a >= 0.999) break;
      }
      n = n.parentElement;
    }
    let base = {r: 7, g: 11, b: 24};
    for (let i = layers.length - 1; i >= 0; i--) {
      const l = layers[i];
      base = {r: l.r * l.a + base.r * (1 - l.a),
              g: l.g * l.a + base.g * (1 - l.a),
              b: l.b * l.a + base.b * (1 - l.a)};
    }
    return `rgb(${Math.round(base.r)}, ${Math.round(base.g)}, ${Math.round(base.b)})`;
  }
  function pathOf(el) {
    const p = [];
    let n = el;
    while (n && n.parentElement) {
      p.unshift(Array.prototype.indexOf.call(n.parentElement.children, n));
      n = n.parentElement;
    }
    return p;
  }
  const elements = textEls.map((el, i) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
      .map(n => n.textContent).join('').trim();
    let parentTextIdx = -1, n = el.parentElement;
    while (n) { if (idx.has(n)) { parentTextIdx = idx.get(n); break; } n = n.parentElement; }
    return {
      idx: i, parentTextIdx, path: pathOf(el),
      tag: el.tagName, id: el.id || '', cls: String(el.className || '').slice(0, 60),
      text: own.slice(0, 80),
      x: r.x, y: r.y, w: r.width, h: r.height,
      opacity: effOpacity(el), fontSize: parseFloat(s.fontSize) || 0,
      fontWeight: s.fontWeight, color: s.color, bg: effBg(el),
      overflowX: el.scrollWidth - el.clientWidth,
      overflowY: el.scrollHeight - el.clientHeight,
    };
  });
  const occEls = Array.from(document.querySelectorAll('.occ'));
  const boxes = occEls.map(el => {
    const r = el.getBoundingClientRect();
    return { id: el.id || '', cls: String(el.className || '').slice(0, 60),
             x: r.x, y: r.y, w: r.width, h: r.height, opacity: effOpacity(el) };
  }).filter(b => b.w > 2 && b.h > 2 && b.opacity > 0.05);
  return {
    vw, vh, elements, boxes,
    duration: (typeof window.SCENE_DURATION === 'number') ? window.SCENE_DURATION : null,
    hasSetTime: typeof window.setTime === 'function',
  };
}
"""


@dataclass
class Problem:
    code: str
    message: str
    severity: str = "error"          # error | warning
    scene: int | None = None
    element: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- color helpers ----------------

def parse_color(css: str) -> tuple[float, float, float, float]:
    """Parse #rgb/#rrggbb/rgb()/rgba() into (r,g,b,a) with 0..255 / 0..1."""
    if not css:
        return (0.0, 0.0, 0.0, 0.0)
    css = css.strip().lower()
    if css in ("transparent", "none"):
        return (0.0, 0.0, 0.0, 0.0)
    if css.startswith("#"):
        h = css[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
        return (0.0, 0.0, 0.0, 0.0)
    m = re.match(r"rgba?\(([^)]+)\)", css)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", ",").split(",") if p.strip()]
        try:
            vals = [float(p) for p in parts[:4]]
        except ValueError:
            return (0.0, 0.0, 0.0, 0.0)
        while len(vals) < 4:
            vals.append(1.0)
        return (vals[0], vals[1], vals[2], vals[3])
    return (0.0, 0.0, 0.0, 0.0)


def _luminance(rgb: tuple[float, float, float]) -> float:
    def chan(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two CSS colors (alpha ignored)."""
    f, b = parse_color(fg), parse_color(bg)
    l1, l2 = _luminance(f), _luminance(b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _is_ancestor(a: dict, b: dict) -> bool:
    pa, pb = a.get("path") or [], b.get("path") or []
    short, long_ = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return bool(short) and long_[:len(short)] == short


def _label(el: dict) -> str:
    ident = el.get("id") or el.get("cls") or el.get("tag", "?")
    return f"{el.get('tag', '?')}#{ident} '{el.get('text', '')[:30]}'"


# ---------------- geometry helpers ----------------

def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cleaned = sorted((a, b) for a, b in intervals if b > a)
    merged: list[list[float]] = []
    for a, b in cleaned:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def occupancy_ratio(boxes: list[dict], frame_height: int) -> float:
    """Fraction of frame height covered by visible .occ blocks (union)."""
    if not boxes or frame_height <= 0:
        return 0.0
    intervals = []
    for r in boxes:
        if r.get("opacity", 1) <= 0.1 or r.get("w", 0) <= 0 or r.get("h", 0) <= 0:
            continue
        top = max(0.0, float(r["y"]))
        bottom = min(float(frame_height), float(r["y"]) + float(r["h"]))
        if bottom > top:
            intervals.append((top, bottom))
    covered = sum(b - a for a, b in merge_intervals(intervals))
    return covered / float(frame_height)


def content_bbox(elements: list[dict], visible_only: bool = True) -> tuple[float, float, float, float] | None:
    """Bounding box (top, bottom, left, right) of visible text content."""
    xs0, ys0, xs1, ys1 = [], [], [], []
    for el in elements:
        if visible_only and el.get("opacity", 0) <= 0.5:
            continue
        if el.get("w", 0) <= 1 or el.get("h", 0) <= 1:
            continue
        xs0.append(float(el["x"]))
        ys0.append(float(el["y"]))
        xs1.append(float(el["x"]) + float(el["w"]))
        ys1.append(float(el["y"]) + float(el["h"]))
    if not xs0:
        return None
    return (min(ys0), max(ys1), min(xs0), max(xs1))


def safe_area_ok(elements: list[dict], vw: int, vh: int, video_cfg: dict,
                 tol: float = 6.0) -> tuple[bool, str]:
    """Check visible text content stays inside the mobile safe area."""
    bbox = content_bbox(elements)
    if bbox is None:
        return False, "no visible content"
    top, bottom, left, right = bbox
    safe_top = vh * float(video_cfg.get("safe_top", 0.08))
    safe_bottom = vh * (1.0 - float(video_cfg.get("safe_bottom", 0.15)))
    gutter = vw * 0.03
    issues = []
    if top < safe_top - tol:
        issues.append(f"top {top:.0f}px above safe line {safe_top:.0f}px")
    if bottom > safe_bottom + tol:
        issues.append(f"bottom {bottom:.0f}px below safe line {safe_bottom:.0f}px")
    if left < gutter - tol:
        issues.append(f"left {left:.0f}px outside gutter")
    if right > vw - gutter + tol:
        issues.append(f"right {right:.0f}px outside gutter")
    return (not issues), "; ".join(issues)


# ---------------- main check entry ----------------

def run_checks(measurement: dict, plan_duration: float, console_errors: list[str],
               frame_stats: list[dict], cfg: dict, default_bg: str = "#000000",
               settled: bool = True) -> list[Problem]:
    """Run all automatic checks on one scene's measurements. Pure function.

    ``settled`` is False for early animation samples: safe-area and occupancy
    are only meaningful once entrance animations have finished.
    """
    cc = cfg.get("checks", {})
    video = cfg.get("video", {})
    problems: list[Problem] = []
    vw = measurement.get("vw", 0)
    vh = measurement.get("vh", 0)
    elements = measurement.get("elements", [])
    boxes = measurement.get("boxes", [])

    # --- structural / runtime ---
    if not measurement.get("hasSetTime"):
        problems.append(Problem("missing_settime", "window.setTime(t) is not defined; scene is not deterministic"))
    measured_dur = measurement.get("duration")
    if measured_dur is None:
        problems.append(Problem("duration_mismatch", "window.SCENE_DURATION is not defined"))
    elif abs(float(measured_dur) - float(plan_duration)) > 0.1:
        problems.append(Problem("duration_mismatch",
                                f"SCENE_DURATION={measured_dur}s but plan says {plan_duration}s"))
    for err in list(dict.fromkeys(console_errors))[:5]:
        problems.append(Problem("console_error", f"JavaScript error: {err[:200]}"))

    # --- blank frames (only after animations should have settled) ---
    for fs in frame_stats:
        if fs.get("fraction", 0) >= 0.4 and \
           fs.get("stddev", 99) < float(cc.get("blank_stddev", 2.0)) and \
           fs.get("colors", 999) <= int(cc.get("blank_max_colors", 8)):
            problems.append(Problem("blank_frame",
                                    f"Frame at {fs['fraction']:.0%} of scene is blank (solid background)"))

    visible = [e for e in elements
               if e.get("opacity", 0) > 0.5 and e.get("w", 0) > 1 and e.get("h", 0) > 1
               and (e.get("text") or "").strip()]
    tol = float(cc.get("edge_tolerance_px", 4))
    min_font = min(vw, vh) * float(cc.get("min_font_ratio", 0.022))

    for el in visible:
        # off-screen / screen-edge overflow
        if el["x"] < -tol or el["y"] < -tol or el["x"] + el["w"] > vw + tol or el["y"] + el["h"] > vh + tol:
            problems.append(Problem("offscreen", f"{_label(el)} extends outside the screen", element=_label(el)))
        # container overflow
        if el.get("overflowX", 0) > 2 or el.get("overflowY", 0) > 2:
            problems.append(Problem("text_overflow",
                                    f"{_label(el)} overflows its container "
                                    f"(+{el.get('overflowX', 0)}px x, +{el.get('overflowY', 0)}px y)",
                                    element=_label(el)))
        # font too small
        if 0 < el.get("fontSize", 0) < min_font:
            problems.append(Problem("small_font",
                                    f"{_label(el)} font {el['fontSize']:.0f}px < minimum {min_font:.0f}px "
                                    f"for this resolution", element=_label(el)))
        # contrast
        bg = el.get("bg") or default_bg
        if parse_color(bg)[3] < 0.05:
            bg = default_bg
        ratio = contrast_ratio(el.get("color", "#fff"), bg)
        large = el.get("fontSize", 0) >= 32 or (
            el.get("fontSize", 0) >= 24 and str(el.get("fontWeight", "400")) in ("700", "800", "900", "bold"))
        need = float(cc.get("min_contrast_large", 3.0)) if large else float(cc.get("min_contrast_small", 4.5))
        if ratio < need:
            problems.append(Problem("low_contrast",
                                    f"{_label(el)} contrast {ratio:.2f}:1 < {need}:1 "
                                    f"({el.get('color')} on {bg})", element=_label(el)))

    # --- overlapping text blocks ---
    threshold = float(cc.get("overlap_threshold", 0.2))
    for i in range(len(visible)):
        for j in range(i + 1, len(visible)):
            a, b = visible[i], visible[j]
            if _is_ancestor(a, b) or a.get("parentTextIdx") == b.get("idx") or b.get("parentTextIdx") == a.get("idx"):
                continue
            if a.get("text") == b.get("text"):
                continue  # duplicated label/shadow text
            ix = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
            iy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
            inter = ix * iy
            smaller = min(a["w"] * a["h"], b["w"] * b["h"])
            if smaller > 0 and inter / smaller > threshold:
                problems.append(Problem("overlap",
                                        f"{_label(a)} overlaps {_label(b)} "
                                        f"({inter / smaller:.0%} of smaller block)"))

    # --- safe area + occupancy (only when the measurement provides .occ boxes) ---
    # Synthetic measurements from older tests omit "boxes"; skip the mobile-specific
    # geometry checks there so the pure typography logic stays independently testable.
    if measurement.get("boxes") is not None and settled:
        ok_safe, safe_reason = safe_area_ok(elements, vw, vh, video, tol=max(tol, 6))
        if not ok_safe:
            problems.append(Problem("safe_area", f"content leaves the mobile safe area: {safe_reason}"))

        min_occ = float(video.get("min_occupancy", 0.55))
        occ = occupancy_ratio(boxes, vh)
        if occ < min_occ:
            problems.append(Problem("low_occupancy",
                                    f"visible content covers {occ:.0%} of frame height < {min_occ:.0%} minimum"))
        measurement["occupancy"] = round(occ, 4)
        measurement["safe_area_ok"] = ok_safe

    # dedupe identical messages
    seen, unique = set(), []
    for p in problems:
        key = (p.code, p.message)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique
