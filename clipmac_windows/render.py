"""FFmpeg cut, vertical render and technical checks for Windows (no macOS tools)."""

import json
import os
import subprocess
import time
from pathlib import Path

from clipmac.captions import write_subtitles
from clipmac.layout import portrait_layout, filter_graph

from .analysis_core import interior_intervals, remap_words
from .live_capture import PROCESS_FLAGS, binary

WINDOWS_FONT = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arialbd.ttf"
RENDER_VERSION = "cm012-windows-render-v1"
AV_TOLERANCE = 0.12


class Cancelled(Exception):
    pass


def run(args, cancel=None, timeout=600, cwd=None, capture=False):
    """Run a tool, honour the cancel event and a deadline, never open a console window."""
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    process = subprocess.Popen([str(a) for a in args], cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                               stderr=subprocess.PIPE, creationflags=PROCESS_FLAGS,
                               text=True, encoding="utf-8", errors="replace")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                out, err = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if (cancel is not None and cancel.is_set()) or time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    raise RuntimeError(f"{Path(str(args[0])).stem}: Zeitlimit erreicht.")
    finally:
        if process.poll() is None:
            process.kill()
    if process.returncode:
        raise RuntimeError(f"{Path(str(args[0])).stem} fehlgeschlagen: {(err or '').strip()[-300:]}")
    return out or ""


def probe(path):
    return json.loads(run([binary("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json",
                           path], capture=True, timeout=60))


def stream_durations(info):
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    def length(stream):
        try:
            return float(stream["duration"])
        except (KeyError, TypeError, ValueError):
            return None
    return video, audio, (length(video) if video else None), (length(audio) if audio else None)


def cut(source, start, duration, output, cancel):
    run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", source,
         "-t", f"{duration:.3f}", "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
         # Equal-length tracks: pad short audio and trim to the requested window (PR #1 lesson).
         "-af", "apad", "-shortest", "-movflags", "+faststart", output], cancel)
    return Path(output)


def quiet_spans(source, duration, cancel):
    """Closed silences only. An open pause at audio EOF carries no silence_end."""
    out = run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-i", source, "-map", "0:a:0", "-vn",
               "-af", "silencedetect=noise=-38dB:d=3,ametadata=mode=print:file=-", "-f", "null", "-"],
              cancel, capture=True, timeout=120)
    spans, start = [], None
    for line in out.splitlines():
        key, _, value = line.strip().partition("=")
        if key == "lavfi.silence_start":
            start = float(value)
        elif key == "lavfi.silence_end" and start is not None:
            end = float(value)
            if 0 <= start < end <= duration:
                spans.append((start, end))
            start = None
    return spans


def tighten(source, output, duration, words, cancel):
    keep = [(0.0, duration)]
    if len(words) >= 2 and duration >= 20.2:
        keep = interior_intervals(duration, words, quiet_spans(source, duration, cancel))
    if len(keep) == 1:
        return Path(source), keep
    parts, joins = [], []
    for i, (a, b) in enumerate(keep):
        parts.extend([f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]",
                      f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d=0.008,afade=t=out:st={max(0, b - a - 0.008):.6f}:d=0.008[a{i}]"])
        joins.append(f"[v{i}][a{i}]")
    parts.append("".join(joins) + f"concat=n={len(keep)}:v=1:a=1[v][a]")
    run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", source, "-filter_complex", ";".join(parts),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", output], cancel)
    return Path(output), keep


def render_vertical(source, folder, words, cfg, channel, cancel):
    """Vertical 1080x1920 with word captions; static per-streamer facecam third if configured."""
    folder = Path(folder)
    info = probe(source)
    video, _, _, _ = stream_durations(info)
    duration = float(info["format"]["duration"])
    face = (cfg.get("facecam_crops") or {}).get(channel)
    layout = portrait_layout(video["width"], video["height"], face if isinstance(face, dict) else None,
                             cfg.get("facecam_share", 1 / 3), "split" if face else None)
    transcript = {"segments": [{"start": 0.0, "end": duration, "text": " ".join(w["word"] for w in words),
                                "words": words}]}
    font = cfg.get("font_path") or WINDOWS_FONT
    captions = write_subtitles(folder / "captions.ass", transcript, font_path=str(font))
    graph = filter_graph(layout)
    # libass on Windows builds may lack fontconfig defaults: ship the measured font beside the ASS file.
    (folder / "fonts").mkdir(exist_ok=True)
    target = folder / "fonts" / Path(font).name
    if not target.exists():
        target.write_bytes(Path(font).read_bytes())
    graph[-1] = graph[-1].replace("subtitles=captions.ass[", "subtitles=captions.ass:fontsdir=fonts[")
    partial = folder / "final.partial.mp4"
    run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", Path(source).resolve(),
         "-filter_complex", ";".join(graph), "-map", "[out]", "-map", "0:a:0",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", partial.name],
        cancel, cwd=folder, timeout=900)
    partial.replace(folder / "final.mp4")
    return {"layout": layout, "captions": captions, "duration": duration}


def thumbnail(video, output, at, cancel):
    run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-ss", f"{max(0, at):.2f}", "-i", video,
         "-frames:v", "1", "-vf", "scale=270:-2", output], cancel)


def technical_check(path, expected_duration, captions=None, words=None):
    """Return a list of blocking errors. Empty list means all checks passed."""
    errors = []
    try:
        info = probe(path)
    except (RuntimeError, ValueError):
        return ["Ausgabe ist nicht decodierbar."]
    video, audio, video_len, audio_len = stream_durations(info)
    if video is None:
        errors.append("Videospur fehlt.")
    elif (video.get("width"), video.get("height")) != (1080, 1920):
        errors.append("Ausgabe ist nicht 1080x1920.")
    if audio is None:
        errors.append("Tonspur fehlt.")
    try:
        total = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        total = None
    if total is None or abs(total - expected_duration) > 0.35:
        errors.append("Dauer stimmt nicht mit dem Schnitt überein.")
    if video_len is not None and audio_len is not None and abs(video_len - audio_len) > AV_TOLERANCE:
        errors.append(f"A/V-Längen weichen um {abs(video_len - audio_len):.2f}s ab.")
    if total is not None and words:
        if any(w["start"] < 0 or w["end"] > total + 0.05 or w["end"] <= w["start"] for w in words):
            errors.append("Untertitelzeiten außerhalb des Clips.")
    for box in (captions or {}).get("bounds", []):
        if box["x"] < 0 or box["y"] < 0 or box["x"] + box["width"] > 1080 or box["y"] + box["height"] > 1920:
            errors.append("Untertitel ragt über den Bildrand.")
            break
    return errors


def edit(source, start, end, words, folder, cfg, channel, cancel):
    """Original excerpt, tightened cut, vertical render, thumbnail and checks."""
    folder = Path(folder)
    duration = round(end - start, 3)
    original = cut(source, start, duration, folder / "original.mp4", cancel)
    relative = [{**w, "start": round(w["start"] - start, 3), "end": round(w["end"] - start, 3)}
                for w in words if start <= w["start"] and w["end"] <= end]
    tightened, keep = tighten(original, folder / "edited.mp4", duration, relative, cancel)
    compact = remap_words(relative, keep)
    kept = round(sum(b - a for a, b in keep), 3)
    rendered = render_vertical(tightened, folder, compact, cfg, channel, cancel)
    thumbnail(folder / "final.mp4", folder / "thumb.jpg", min(kept / 2, 3), cancel)
    errors = technical_check(folder / "final.mp4", kept, rendered["captions"], compact)
    return {"render_version": RENDER_VERSION, "source_start": start, "source_end": end,
            "kept_intervals": keep, "duration": kept, "words": len(compact), "layout": rendered["layout"]["mode"],
            "technical_errors": errors}
