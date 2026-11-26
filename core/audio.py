"""Audio stage: voiceover, procedural music/SFX, ducking and -14 LUFS mastering.

Everything here degrades gracefully. TTS is optional (edge-tts needs network); if
it fails we still master a music+SFX bed so the MP4 is never silent. All music and
SFX are generated in code (numpy) so the pipeline works fully offline.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import wave
from pathlib import Path

import numpy as np

from .renderer import find_ffmpeg

log = logging.getLogger("motionforge.audio")

SR = 44100


# ------------------------------------------------------------------ io helpers

def _decode(path: Path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 using the bundled ffmpeg."""
    ffmpeg = find_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "s16le",
         "-ac", "1", "-ar", str(sr), "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg could not decode {path}: {proc.stderr[-400:]!r}")
    data = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return data


def _write_wav(path: Path, samples: np.ndarray, sr: int = SR):
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _fit_to_scene(src: Path, dst: Path, max_seconds: float, sr: int = SR) -> Path:
    """Decode, speed up if needed (max 1.45x), trim/pad, and write a scene WAV.

    The old version returned an unwritten path whenever no speed-up was needed,
    silently dropping that scene's voiceover.
    """
    data = _decode(src, sr)
    dur = len(data) / sr
    if dur > max_seconds and max_seconds > 0.2:
        tempo = min(1.45, dur / max_seconds)
        speed = subprocess.run(
            [find_ffmpeg(), "-y", "-v", "error", "-i", str(src), "-filter:a",
             f"atempo={tempo:.4f}", "-ac", "1", "-ar", str(sr), str(dst)],
            capture_output=True, text=True,
        )
        if speed.returncode == 0 and dst.exists():
            data = _decode(dst, sr)
    if max_seconds > 0.2:
        target = int(max_seconds * sr)
        if len(data) > target:
            data = data[:target]
        elif len(data) < target:
            data = np.pad(data, (0, target - len(data)))
    _write_wav(dst, data, sr)
    return dst


# ------------------------------------------------------------------ tts

def _run_async(coro_factory, timeout: float = 45):
    """Run a coroutine on a private event loop in a worker thread.

    Playwright's sync API can leave an event loop active in the calling thread
    while a renderer is open, which makes ``asyncio.run`` fail inside the
    pipeline even though TTS works standalone. A dedicated thread sidesteps it.
    """
    result: dict = {}

    def runner():
        try:
            async def with_timeout():
                return await asyncio.wait_for(coro_factory(), timeout=timeout)
            result["value"] = asyncio.run(with_timeout())
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout + 10)
    if thread.is_alive():
        raise TimeoutError(f"TTS worker exceeded {timeout:.0f}s")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def synthesize_scenes(scenes: list[dict], out_dir: Path, voice: str, rate: str,
                      enabled: bool = True) -> dict:
    """Create one MP3 per scene. Returns a report; never raises."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"enabled": bool(enabled), "voice": voice, "rate": rate,
              "segments": [], "failed": [], "available": False}
    if not enabled:
        return report
    for i, scene in enumerate(scenes, start=1):
        text = (scene.get("narration") or "").strip()
        if not text:
            continue
        path = out_dir / f"scene_{i:02d}.mp3"

        async def speak(text=text, path=path):
            import edge_tts  # optional dependency
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(path))

        try:
            _run_async(speak, timeout=45)
            if path.exists() and path.stat().st_size > 500:
                report["segments"].append({"scene": i, "path": str(path),
                                           "bytes": path.stat().st_size})
            else:
                report["failed"].append({"scene": i, "reason": "empty mp3"})
        except Exception as exc:  # noqa: BLE001
            report["failed"].append({"scene": i, "reason": str(exc)[:160]})
            log.warning("TTS scene %d failed (%s); continuing without voiceover", i, str(exc)[:120])
            # The endpoint is flaky/offline: stop trying and use the music bed.
            break
    report["available"] = bool(report["segments"])
    return report


# ------------------------------------------------------------------ music/sfx

def generate_music(duration: float, sr: int = SR) -> np.ndarray:
    """Minimal dark-navy ambient bed: slow chord pad plus a soft pulse."""
    n = max(1, int(duration * sr))
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    chords = [
        (220.00, 261.63, 329.63),   # Am
        (174.61, 220.00, 261.63),   # F
        (261.63, 329.63, 392.00),   # C
        (196.00, 246.94, 293.66),   # G
    ]
    seg = 4.0
    for start in np.arange(0, duration, seg):
        a = int(start * sr)
        b = int(min(duration, start + seg) * sr)
        if b <= a:
            continue
        local = (np.arange(b - a, dtype=np.float32) / sr)
        env = np.minimum(1.0, local / 0.9) * np.minimum(1.0, (seg - local) / 0.9)
        freqs = chords[int(start // seg) % len(chords)]
        wave_ = np.zeros(b - a, dtype=np.float32)
        for k, f in enumerate(freqs):
            wave_ += np.sin(2 * np.pi * f * local + k * 0.7).astype(np.float32)
            wave_ += 0.35 * np.sin(2 * np.pi * (f * 2.0) * local).astype(np.float32)
        out[a:b] += (wave_ / (len(freqs) * 1.35)) * env * 0.32
    # Soft sub pulse at 120 bpm.
    beat = 0.5
    pulse = np.exp(-((t % beat) / 0.085)).astype(np.float32)
    out += 0.10 * pulse * np.sin(2 * np.pi * 55 * t).astype(np.float32)
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.55).astype(np.float32)


def generate_whoosh(duration: float = 0.35, sr: int = SR) -> np.ndarray:
    n = max(1, int(duration * sr))
    t = np.arange(n, dtype=np.float32) / sr
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, n).astype(np.float32)
    # Cheap low-pass to make it a whoosh rather than a hiss.
    smooth = np.copy(noise)
    for i in range(1, n):
        smooth[i] = 0.82 * smooth[i - 1] + 0.18 * noise[i]
    env = np.sin(np.pi * t / duration) ** 2
    return (smooth * env * 0.5).astype(np.float32)


def generate_chime(duration: float = 0.9, sr: int = SR) -> np.ndarray:
    n = max(1, int(duration * sr))
    t = np.arange(n, dtype=np.float32) / sr
    env = np.exp(-t * 5.5)
    tone = (np.sin(2 * np.pi * 880 * t) + 0.55 * np.sin(2 * np.pi * 1320 * t)
            + 0.25 * np.sin(2 * np.pi * 1760 * t))
    return (tone * env * 0.30).astype(np.float32)


def generate_tick(sr: int = SR) -> np.ndarray:
    n = int(0.06 * sr)
    t = np.arange(n, dtype=np.float32) / sr
    return (np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 60) * 0.25).astype(np.float32)


def _place(buf: np.ndarray, clip: np.ndarray, at: float, gain: float, sr: int = SR):
    start = int(max(0.0, at) * sr)
    if start >= len(buf):
        return
    end = min(len(buf), start + len(clip))
    buf[start:end] += clip[: end - start] * gain


# ------------------------------------------------------------------ mastering

def _loudnorm(src: Path, dst: Path, target_lufs: float = -14.0) -> bool:
    proc = subprocess.run(
        [find_ffmpeg(), "-y", "-v", "error", "-i", str(src), "-af",
         f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "2", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not dst.exists():
        log.warning("loudnorm failed (%s); keeping the raw mix", proc.stderr[-300:])
        return False
    return True


# ------------------------------------------------------------------ stage entry

def build_audio(run_dir: Path, storyboard: dict, cfg: dict, *,
                external_voiceover: Path | None = None, external_music: Path | None = None,
                tts_enabled: bool | None = None) -> dict:
    """Build the full soundtrack and return a report with an audio path."""
    run_dir = Path(run_dir)
    audio_dir = run_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    acfg = cfg.get("audio", {})
    scenes = storyboard.get("scenes") or []
    durations = [float(s.get("duration") or 0) for s in scenes]
    total = max(0.5, sum(durations))
    n = int(total * SR)
    music = np.zeros(n, dtype=np.float32)
    voice = np.zeros(n, dtype=np.float32)
    sfx = np.zeros(n, dtype=np.float32)

    # ---- music bed ----
    music_source = "generated"
    if external_music and Path(external_music).exists():
        try:
            raw = _decode(Path(external_music), SR)
            if len(raw) < n:
                raw = np.tile(raw, int(np.ceil(n / max(1, len(raw)))))
            music = raw[:n].astype(np.float32)
            music_source = str(external_music)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not decode music (%s); using generated bed", exc)
    if music_source == "generated":
        music = generate_music(total, SR)

    # ---- voiceover ----
    tts_report = {"enabled": False, "segments": [], "failed": [], "available": False,
                  "voice": acfg.get("tts_voice"), "rate": acfg.get("tts_rate")}
    speech_mask = np.zeros(n, dtype=np.float32)
    if external_voiceover and Path(external_voiceover).exists():
        try:
            raw = _decode(Path(external_voiceover), SR)
            voice[: min(n, len(raw))] = raw[:n]
            speech_mask[: min(n, len(raw))] = 1.0
            tts_report = {"enabled": False, "external": str(external_voiceover),
                          "segments": [{"scene": 0, "path": str(external_voiceover)}],
                          "failed": [], "available": True,
                          "voice": None, "rate": None}
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not decode voiceover (%s)", exc)
    else:
        enabled = bool(acfg.get("tts_enabled", True)) if tts_enabled is None else bool(tts_enabled)
        tts_report = synthesize_scenes(scenes, audio_dir / "voice",
                                       acfg.get("tts_voice", "en-US-GuyNeural"),
                                       acfg.get("tts_rate", "+8%"), enabled=enabled)
        if tts_report.get("available"):
            by_scene = {s["scene"]: s["path"] for s in tts_report["segments"]}
            cursor = 0.0
            for i, (scene, dur) in enumerate(zip(scenes, durations), start=1):
                seg = by_scene.get(i)
                if seg:
                    fitted = _fit_to_scene(Path(seg), audio_dir / f"fit_{i:02d}.wav",
                                           max(0.2, dur - 0.08))
                    try:
                        clip = _decode(fitted, SR)
                        _place(voice, clip, cursor + 0.06, 1.0, SR)
                        a = int((cursor + 0.06) * SR)
                        b = min(n, a + len(clip))
                        speech_mask[a:b] = 1.0
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Voice clip %d could not be decoded (%s)", i, exc)
                cursor += dur
        else:
            log.warning("No voiceover available; mastering music + SFX only")

    # ---- sfx ----
    whoosh = generate_whoosh()
    chime = generate_chime()
    tick = generate_tick()
    sfx_events = 0
    cursor = 0.0
    for scene, dur in zip(scenes, durations):
        _place(sfx, whoosh, max(0.0, cursor - 0.12), float(acfg.get("sfx_volume", 0.5)) * 0.7)
        if scene.get("tag") in ("ANSWER", "SOLUTION"):
            _place(sfx, chime, cursor + 0.05, float(acfg.get("sfx_volume", 0.5)))
        if scene.get("component") == "countdown":
            for k in range(max(1, int(dur))):
                _place(sfx, tick, cursor + k, float(acfg.get("sfx_volume", 0.5)) * 0.6)
        cursor += dur
        sfx_events += 1

    # ---- ducking ----
    ducked = False
    if speech_mask.any():
        win = max(1, int(0.28 * SR))
        kernel = np.ones(win, dtype=np.float32) / win
        smooth = np.convolve(speech_mask, kernel, mode="same")
        duck_gain = 1.0 - 0.62 * np.clip(smooth, 0, 1)
        music_gain = float(acfg.get("music_volume", 0.18))
        music = music * duck_gain.astype(np.float32) * music_gain
        ducked = True
    else:
        music = music * float(acfg.get("music_volume", 0.18))

    mix = np.clip(voice + music + sfx, -1.2, 1.2)
    mix = np.tanh(mix * 0.95).astype(np.float32)
    raw_path = audio_dir / "mix_raw.wav"
    _write_wav(raw_path, mix, SR)

    master = audio_dir / "audio.wav"
    normalized = _loudnorm(raw_path, master, float(acfg.get("target_lufs", -14)))
    if not normalized:
        shutil.copyfile(raw_path, master)

    report = {
        "path": str(master),
        "raw_mix": str(raw_path),
        "duration": round(total, 3),
        "voiceover": bool(tts_report.get("available")),
        "tts": tts_report,
        "music": music_source,
        "sfx_events": sfx_events,
        "ducked": ducked,
        "target_lufs": float(acfg.get("target_lufs", -14)),
        "loudnorm": normalized,
        "alignment": "estimated",
    }
    log.info("Audio: %.1fs | voice=%s | music=%s | ducked=%s | loudnorm=%s | %s",
             total, report["voiceover"], music_source, ducked, normalized, master.name)
    return report
