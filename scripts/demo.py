"""Offline speech + video fixture; never discovers or uploads real content."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clipmac.media import binary, process, run, probe
from clipmac.state import RUNTIME, settings, atomic_json

directory = RUNTIME / "demo"
directory.mkdir(parents=True, exist_ok=True)
first = "Hallo zusammen. Heute testen wir automatische Untertitel auf diesem Mac."
second = "Die lange Pause wird herausgeschnitten. Das fertige Video ist im Hochformat."
for name, text in [("first", first), ("second", second)]:
    run(["/usr/bin/say", "-v", "Anna", "-r", "170", "-o", directory / f"{name}.aiff", text])
run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", directory / "first.aiff",
     "-f", "lavfi", "-t", "2.5", "-i", "anullsrc=r=22050:cl=mono", "-i", directory / "second.aiff",
     "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]", "-map", "[a]", directory / "speech.wav"])
duration = float(probe(directory / "speech.wav")["format"]["duration"])
run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
     "-i", directory / "speech.wav", "-t", str(duration), "-c:v", "libx264", "-preset", "veryfast",
     "-threads", "4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", directory / "source.mp4"])
clip = {"id": "local-demo", "broadcaster_name": "ClipMac Test", "title": "Untertitel und Pausenschnitt auf dem Mac testen", "url": ""}
started = time.time()
result = process(directory / "source.mp4", directory, clip, settings(), print)
assert result["render"]["width"] == 1080 and result["render"]["height"] == 1920
assert result["edit"]["original_seconds"] - result["edit"]["kept_seconds"] > 1.5
assert result["subtitle_words"] >= 15, result
assert result["metadata"]["title"] and result["metadata"]["hashtags"]
report = {"elapsed_seconds": round(time.time()-started, 2), "result": result, "checks": "Hochformat, Audio, Pausenschnitt, echte Whisper-Untertitel, lokale KI-Metadaten"}
atomic_json(directory / "validation.json", report)
print(json.dumps(report, ensure_ascii=False, indent=2))
