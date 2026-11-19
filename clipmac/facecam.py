import contextlib
import json
import sys
import subprocess
from pathlib import Path

from .media import binary, probe
from facecam_detector import detect_facecam_config, sample_detection_frames


def detect_timeline(path, video, duration):
    import cv2
    from facecam_detector import _detect_faces, _load_face_detector
    from .scenes import timeline_from_samples
    cv2.setNumThreads(2)
    if _load_face_detector() is None:
        raise RuntimeError("Gesichtserkennung für Fullcam-Wechsel ist nicht verfügbar.")
    width = 640
    height = max(2, round(video["height"] * width / video["width"] / 2) * 2)
    command = [binary("ffmpeg"), "-v", "error", "-nostdin", "-i", str(path),
               "-vf", f"fps=2:start_time=0,scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    samples = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        while True:
            frame = proc.stdout.read(width * height * 3)
            if not frame:
                break
            if len(frame) != width * height * 3:
                raise RuntimeError("Unvollständiges Bild bei der Layout-Erkennung.")
            samples.append({"t": len(samples) / 2, "faces": _detect_faces((width, height, frame))})
        error = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError("Layout-Bildanalyse fehlgeschlagen: " + error[-500:])
    return timeline_from_samples(samples, duration)


def main():
    path = Path(sys.argv[1])
    streamer = sys.argv[2]
    meta = probe(path)
    video = next(s for s in meta["streams"] if s["codec_type"] == "video")
    if "--timeline" in sys.argv:
        with contextlib.redirect_stdout(sys.stderr):
            timeline = detect_timeline(path, video, float(meta["format"]["duration"]))
        print(json.dumps(timeline))
        return
    with contextlib.redirect_stdout(sys.stderr):
        frames = sample_detection_frames(input_path=path, ffmpeg_path=binary("ffmpeg"), ffprobe_path=binary("ffprobe"))
        face = detect_facecam_config(streamer_name=streamer, frames=frames, source_width=video["width"], source_height=video["height"])
    print(json.dumps(face.crop if face else None))


if __name__ == "__main__":
    main()
