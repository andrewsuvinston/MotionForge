"""Deterministic renderer: Playwright frame capture + FFmpeg encode.

Preview mode keeps the full CSS viewport but halves the device scale factor,
so layout is identical to the final render while screenshots are half-size.
"""
from __future__ import annotations

import io
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright
from tqdm import tqdm

from .checks import MEASURE_JS
from .config import resolution_for

log = logging.getLogger("motionforge.renderer")


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("FFmpeg not found on PATH and imageio-ffmpeg is not installed") from exc


def frame_stats(png_path: Path, fraction: float) -> dict:
    """Cheap blank-frame detection: grayscale stddev + distinct color count."""
    with Image.open(png_path) as im:
        gray = im.convert("L")
        stddev = ImageStat.Stat(gray).stddev[0]
        colors = gray.getcolors(maxcolors=4096)
        n_colors = len(colors) if colors is not None else 4097
    return {"fraction": fraction, "stddev": float(stddev), "colors": n_colors}


@dataclass
class SampleResult:
    frames: list[dict] = field(default_factory=list)        # {fraction, t, path}
    measurements: list[dict] = field(default_factory=list)  # DOM measurements at 50%/75%
    console_errors: list[str] = field(default_factory=list)
    frame_stats: list[dict] = field(default_factory=list)
    load_error: str | None = None


class Renderer:
    def __init__(self, cfg: dict, ratio: str, preview: bool = False):
        self.cfg = cfg
        self.width, self.height = resolution_for(cfg, ratio)
        self.preview = preview
        video_cfg = cfg.get("video", {})
        legacy = cfg.get("render", {})
        self.fps = int(video_cfg.get("preview_fps", legacy.get("preview_fps", 15)) if preview
                       else video_cfg.get("fps", legacy.get("fps", 30)))
        self.dsf = 0.5 if preview else 1.0
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._console_errors: list[str] = []

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=[
            "--force-color-profile=srgb", "--hide-scrollbars",
            "--disable-lcd-text", "--font-render-hinting=none",
        ])
        self._context = self._browser.new_context(
            viewport={"width": self.width, "height": self.height},
            device_scale_factor=self.dsf,
        )
        # Fully offline rendering: block every network request.
        def _route(route):
            url = route.request.url
            if url.startswith(("file://", "data:", "blob:", "about:")):
                route.continue_()
            else:
                log.warning("Blocked network request inside scene: %s", url[:120])
                route.abort()
        self._context.route("**/*", _route)
        self._page = self._context.new_page()
        self._page.on("console", lambda msg: self._console_errors.append(msg.text)
                      if msg.type == "error" else None)
        self._page.on("pageerror", lambda exc: self._console_errors.append(str(exc)))
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _load(self, html_path: Path):
        self._console_errors = []
        self._page.goto(html_path.resolve().as_uri(), wait_until="load")
        if not self._page.evaluate("() => typeof window.setTime === 'function'"):
            raise RuntimeError(f"{html_path.name} does not define window.setTime(t)")
        self._page.evaluate("() => window.setTime(0)")

    def _set_time(self, t: float):
        self._page.evaluate("(t) => window.setTime(t)", t)

    def _shot(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(path), animations="disabled", caret="hide")

    # ---------------- sampling for the check loop ----------------

    def capture_samples(self, html_path: Path, duration: float, out_dir: Path) -> SampleResult:
        result = SampleResult()
        try:
            self._load(html_path)
        except Exception as exc:  # noqa: BLE001
            result.load_error = str(exc)
            return result
        fractions = self.cfg["loop"]["sample_fractions"]
        for f in fractions:
            t = round(f * duration, 4)
            try:
                self._set_time(t)
            except Exception as exc:  # noqa: BLE001
                result.console_errors.append(f"setTime({t}) raised: {exc}")
                continue
            path = out_dir / f"sample_{int(f * 100):02d}.png"
            self._shot(path)
            result.frames.append({"fraction": f, "t": t, "path": str(path)})
            result.frame_stats.append(frame_stats(path, f))
        for f in (0.5, 0.75):
            try:
                self._set_time(round(f * duration, 4))
                m = self._page.evaluate(MEASURE_JS)
                m["fraction"] = f
                result.measurements.append(m)
            except Exception as exc:  # noqa: BLE001
                result.console_errors.append(f"measurement at {f} failed: {exc}")
        result.console_errors.extend(self._console_errors)
        return result

    # ---------------- final full render ----------------

    def render_frames(self, scenes: list[tuple[Path, float]], frames_dir: Path) -> int:
        """Render every frame of every scene into frames_dir as %06d.png."""
        frames_dir.mkdir(parents=True, exist_ok=True)
        for old in frames_dir.glob("*.png"):
            old.unlink()
        idx = 0
        for scene_no, (html_path, duration) in enumerate(scenes, start=1):
            self._load(html_path)
            n = max(1, round(duration * self.fps))
            for i in tqdm(range(n), desc=f"Render scene {scene_no}", unit="frame", leave=False):
                self._set_time(i / self.fps)
                self._shot(frames_dir / f"{idx:06d}.png")
                idx += 1
        return idx

    # ---------------- encoding ----------------

    def encode(self, frames_dir: Path, out_path: Path,
               voiceover: Path | None = None, music: Path | None = None,
               audio_path: Path | None = None) -> Path:
        ffmpeg = find_ffmpeg()
        cmd = [ffmpeg, "-y", "-framerate", str(self.fps), "-i", str(frames_dir / "%06d.png")]
        if audio_path and Path(audio_path).exists():
            cmd += ["-i", str(audio_path), "-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "192k", "-shortest"]
        elif voiceover and music:
            cmd += ["-i", str(voiceover), "-i", str(music),
                    "-filter_complex", "[2:a]volume=0.25[m];[1:a][m]amix=inputs=2:duration=first[a]",
                    "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        elif voiceover:
            cmd += ["-i", str(voiceover), "-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "192k", "-shortest"]
        elif music:
            cmd += ["-i", str(music), "-map", "0:v", "-map", "1:a",
                    "-af", "volume=0.3", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                "-preset", "medium", "-movflags", "+faststart", str(out_path)]
        log.info("Encoding: %s", " ".join(cmd[:8]) + " ...")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out_path.exists():
            raise RuntimeError(f"FFmpeg failed (code {proc.returncode}):\n{proc.stderr[-2000:]}")
        log.info("Encoded %s (%.1f MB)", out_path.name, out_path.stat().st_size / 1e6)
        return out_path
