"""Layout engine: mobile safe areas, font scaling, occupancy measurement.

All sizes are computed for the full CSS viewport (1080x1920 for 9:16). Preview
renders at half device scale but identical CSS layout, so typography rules hold.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameLayout:
    width: int
    height: int
    safe_top: int
    safe_bottom: int
    headline_px: int
    body_px: int
    caption_px: int
    min_font_px: int
    gutter_px: int
    gap_px: int

    @property
    def content_top(self) -> int:
        return self.safe_top

    @property
    def content_bottom(self) -> int:
        return self.height - self.safe_bottom

    @property
    def content_height(self) -> int:
        return max(0, self.content_bottom - self.content_top)


def scale_for_frame(px_at_1080: int, frame_min_side: int) -> int:
    """Scale a size designed at 1080 to the frame's short side."""
    return max(1, round(px_at_1080 * frame_min_side / 1080))


def compute_layout(width: int, height: int, video_cfg: dict) -> FrameLayout:
    short = min(width, height)
    top = round(height * float(video_cfg.get("safe_top", 0.08)))
    bottom = round(height * float(video_cfg.get("safe_bottom", 0.15)))
    return FrameLayout(
        width=width, height=height,
        safe_top=top, safe_bottom=bottom,
        headline_px=scale_for_frame(int(video_cfg.get("headline_px", 84)), short),
        body_px=scale_for_frame(int(video_cfg.get("body_px", 52)), short),
        caption_px=scale_for_frame(int(video_cfg.get("caption_px", 50)), short),
        min_font_px=scale_for_frame(int(video_cfg.get("min_font_px", 40)), short),
        gutter_px=round(width * 0.06),
        gap_px=round(short * 0.02),
    )


def css_variables(layout: FrameLayout) -> str:
    return "\n".join([
        f"--w:{layout.width}px; --h:{layout.height}px;",
        f"--safe-top:{layout.safe_top}px; --safe-bottom:{layout.safe_bottom}px;",
        f"--headline:{layout.headline_px}px; --body:{layout.body_px}px;",
        f"--caption:{layout.caption_px}px; --min-font:{layout.min_font_px}px;",
        f"--gutter:{layout.gutter_px}px; --gap:{layout.gap_px}px;",
    ])


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cleaned = sorted((a, b) for a, b in intervals if b > a)
    merged: list[list[float]] = []
    for a, b in cleaned:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def occupancy_ratio(rects: list[dict], frame_height: int) -> float:
    """Fraction of frame height covered by visible content boxes (union)."""
    if not rects or frame_height <= 0:
        return 0.0
    intervals = []
    for r in rects:
        if r.get("opacity", 1) <= 0.1 or r.get("w", 0) <= 0 or r.get("h", 0) <= 0:
            continue
        top = max(0.0, float(r["y"]))
        bottom = min(float(frame_height), float(r["y"]) + float(r["h"]))
        if bottom > top:
            intervals.append((top, bottom))
    covered = sum(b - a for a, b in merge_intervals(intervals))
    return covered / float(frame_height)


def occupancy_ok(rects: list[dict], frame_height: int, min_ratio: float = 0.55) -> tuple[bool, float]:
    ratio = occupancy_ratio(rects, frame_height)
    return ratio >= min_ratio, ratio


def vertical_stack_plan(n_items: int, area_height: int, gap: int) -> list[dict]:
    """Simple centered vertical distribution plan (used by tests and components)."""
    if n_items <= 0:
        return []
    total_gap = gap * (n_items - 1)
    item_h = max(1, (area_height - total_gap) // n_items)
    plan = []
    y = 0
    for i in range(n_items):
        plan.append({"index": i, "y": y, "height": item_h})
        y += item_h + gap
    return plan
