from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .state import ROOT, atomic_json

EDGE_SILENCE_MIN_SECONDS = 0.35
# FFmpeg rounds the timestamps written by silencedetect.
SILENCE_TIMESTAMP_TOLERANCE = 0.0001

# Upstream also contains a tiktok_uploader.py. Keep installed packages first.
sys.path.append(str(ROOT / "upstream-twitch-clipper" / "src"))


def binary(name):
    local = Path("/opt/homebrew/opt/ffmpeg-full/bin") / name
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} fehlt. Bitte FFmpeg installieren.")
    return found


def run(args, cwd=None, timeout=1800):
    p = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name}: {(p.stderr or p.stdout)[-2500:]}")
    return p


def probe(path):
    return json.loads(run([binary("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path]).stdout)


def silence_intervals(metadata, duration):
    """Read silence events in clip time. An open interval reaches audio EOF."""
    intervals = []
    start = None
    pattern = r"^lavfi\.silence_(start|end)=(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)$"
    for match in re.finditer(pattern, metadata, re.MULTILINE):
        kind = match.group(1)
        value = min(duration, max(0.0, float(match.group(2))))
        if kind == "start":
            start = value
        elif start is not None:
            intervals.append((start, value))
            start = None
    if start is not None:
        intervals.append((start, None))
    return intervals


def keep_intervals(silences, duration, padding=0.15, *, min_interior_seconds=0.0):
    """Keep padding beside audible material and remove silence at the outer boundaries."""
    keep, cursor = [], 0.0
    for start, end in silences:
        at_start = start <= SILENCE_TIMESTAMP_TOLERANCE
        at_end = end is None
        if not (at_start or at_end) and end - start + SILENCE_TIMESTAMP_TOLERANCE < min_interior_seconds:
            continue
        cut_start = cursor if at_start else min(duration, max(cursor, start + padding))
        cut_end = duration if at_end else min(duration, max(cut_start, end - padding))
        if cut_end - cut_start < 0.1:
            continue
        if cut_start - cursor > 0.04:
            keep.append((cursor, cut_start))
        cursor = cut_end
    if duration - cursor > 0.04:
        keep.append((cursor, duration))
    if sum(e - s for s, e in keep) < 1:
        raise RuntimeError("Clip enthält fast nur Stille; wird nicht automatisch veröffentlicht.")
    return keep


def cut_silence(source, output, cfg):
    info = probe(source)
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise RuntimeError("Der Clip hat keine Audiospur.")
    duration = float(info["format"]["duration"])
    if not 1 <= duration <= 190:
        raise RuntimeError("Erwartet wird ein Clip bis 3 Minuten, kein vollständiger Stream.")
    interior_min = cfg["silence_min_seconds"]
    detect_min = min(EDGE_SILENCE_MIN_SECONDS, interior_min)
    # Only a frame with returning sound carries silence_end metadata. FFmpeg's
    # diagnostic log prints an end timestamp at audio EOF too.
    filters = (f"silencedetect=noise={cfg['silence_db']}dB:d={detect_min},"
               "ametadata=mode=print:file=-")
    analysis = run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-i", source, "-map", "0:a:0",
                    "-af", filters, "-vn", "-f", "null", "-"])
    spans = keep_intervals(silence_intervals(analysis.stdout, duration), duration,
                           cfg["silence_padding_seconds"], min_interior_seconds=interior_min)
    parts, joins = [], []
    for i, (a, b) in enumerate(spans):
        parts.extend([f"[0:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS[v{i}]",
                      f"[0:a]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS,afade=t=in:d=0.008,afade=t=out:st={max(0,b-a-.008):.6f}:d=0.008[a{i}]"])
        joins.append(f"[v{i}][a{i}]")
    parts.append("".join(joins) + f"concat=n={len(spans)}:v=1:a=1[v][a]")
    run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", source,
         "-filter_complex_threads", "2", "-filter_complex", ";".join(parts),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-threads", "4", "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", output])
    return {"original_seconds": duration, "kept_seconds": sum(b - a for a, b in spans),
            "kept_intervals": spans, "audio_join_fade_ms": 8, "silence_cut_version": 2}


_whisper = None
_whisper_name = None


def transcribe(source, cfg):
    global _whisper, _whisper_name
    from faster_whisper import WhisperModel
    if _whisper is None or _whisper_name != cfg["whisper_model"]:
        _whisper = WhisperModel(cfg["whisper_model"], device="cpu", compute_type="int8", cpu_threads=4,
                                download_root=str(ROOT / "models" / "whisper"), local_files_only=True)
        _whisper_name = cfg["whisper_model"]
    segments, info = _whisper.transcribe(str(source), language=cfg["language"], vad_filter=True,
                                        word_timestamps=True, condition_on_previous_text=False)
    data = [{"start": s.start, "end": s.end, "text": s.text.strip(),
             "words": [{"start": w.start, "end": w.end, "word": w.word.strip()} for w in s.words or []]}
            for s in segments if s.no_speech_prob < 0.8 and s.text.strip()]
    return {"language": info.language, "segments": data, "text": " ".join(s["text"] for s in data)}


# Keep the public helpers available for existing callers and exported captions.
from .captions import ass_time, safe_ass, write_subtitles


def render_vertical(source, directory, cfg, streamer):
    from config import validate_facecam_crop
    from .layout import portrait_layout, timeline_filter_graph
    meta = probe(source)
    video = next(s for s in meta["streams"] if s["codec_type"] == "video")
    duration = float(meta["format"]["duration"])
    if cfg["facecam"]:
        # OpenCV remains isolated from Whisper/PyAV's macOS media libraries.
        detected = run([sys.executable, "-m", "clipmac.facecam", source.resolve(), streamer, "--timeline"],
                       cwd=ROOT, timeout=180)
        timeline = json.loads(detected.stdout)
        static_crop = validate_facecam_crop(cfg.get("facecam_crops", {}).get(streamer))
        for section in timeline:
            if static_crop and section["mode"] == "split":
                section["face"] = static_crop
    else:
        timeline = [{"start": 0.0, "end": duration, "mode": "portrait", "face": None}]
    for section in timeline:
        section["layout"] = portrait_layout(video["width"], video["height"], section["face"],
                                             cfg.get("facecam_share", 1 / 3), section["mode"])
    graph = timeline_filter_graph(timeline)
    face = next((s["face"] for s in timeline if s["face"]), None)
    layout = timeline[0]["layout"]
    atomic_json(directory / "layout-timeline.json", timeline)
    temp = directory / "final.partial.mp4"
    run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", source.resolve(),
         "-filter_complex_threads", "2", "-filter_complex", ";".join(graph),
         "-map", "[out]", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-threads", "4", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-movflags", "+faststart", temp.resolve()], cwd=directory)
    checked = probe(temp)
    v = next(s for s in checked["streams"] if s["codec_type"] == "video")
    if (v["width"], v["height"]) != (1080, 1920) or not any(s["codec_type"] == "audio" for s in checked["streams"]):
        raise RuntimeError("Ausgabeprüfung fehlgeschlagen: Hochformat oder Audio fehlt.")
    if abs(float(checked["format"]["duration"]) - float(meta["format"]["duration"])) > 0.3:
        raise RuntimeError("Ausgabeprüfung fehlgeschlagen: Videolänge stimmt nicht.")
    temp.replace(directory / "final.mp4")
    return {"width": 1080, "height": 1920, "duration": float(checked["format"]["duration"]),
            "facecam_detected": face is not None, "facecam_crop": face,
            "layout_version": 4, "scaler": "lanczos", "video_crf": 18, "layout": layout, "timeline": timeline}


def download(clip, directory):
    output = directory / "source.mp4"
    if output.exists():
        probe(output)
        return output
    from urllib.parse import urlparse
    url = urlparse(clip["url"])
    if url.scheme != "https" or url.hostname not in {"clips.twitch.tv", "www.twitch.tv", "twitch.tv"}:
        raise ValueError("Erwartet wird ein Twitch-Clip-Link.")
    run([sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-progress",
         "--socket-timeout", "30", "--retries", "3", "--max-filesize", "500M",
         "--ffmpeg-location", str(Path(binary("ffmpeg")).parent),
         "-f", "best[ext=mp4]/best", "--remux-video", "mp4", "-o", str(directory / "source.%(ext)s"), "--", clip["url"]])
    if not output.exists():
        raise RuntimeError("Download hat keine MP4 erzeugt.")
    probe(output)
    return output


def process(source, directory, clip, cfg, log):
    from .metadata import generate_metadata
    directory.mkdir(parents=True, exist_ok=True)
    edited = directory / "edited.mp4"
    log(f"{clip['broadcaster_name']}: Stille kürzen")
    cut = cut_silence(source, edited, cfg)
    log(f"{clip['broadcaster_name']}: deutsche Untertitel erkennen")
    transcript = transcribe(edited, cfg)
    atomic_json(directory / "transcript.json", transcript)
    caption_info = write_subtitles(directory / "captions.ass", transcript)
    atomic_json(directory / "caption-layout.json", caption_info)
    log(f"{clip['broadcaster_name']}: Titel und Hashtags lokal erzeugen")
    metadata = generate_metadata(transcript, clip, cfg)
    atomic_json(directory / "metadata.json", metadata)
    log(f"{clip['broadcaster_name']}: Hochformat rendern")
    rendering = render_vertical(edited, directory, cfg, clip["broadcaster_name"].lower())
    result = {"file": str((directory / "final.mp4").resolve()), "metadata": metadata,
              "edit": cut, "render": rendering, "caption_version": caption_info["version"], "caption_style": caption_info["style"], "subtitle_words": sum(len(s["words"]) for s in transcript["segments"])}
    atomic_json(directory / "result.json", result)
    return result
