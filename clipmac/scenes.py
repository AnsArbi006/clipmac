"""Conservative, temporal layout decisions from visual face detections only."""
from statistics import median


def classify_faces(faces):
    faces = [f for f in faces if f.get("score", 1) >= .65 and f["w"] >= .04]
    corners = [f for f in faces if (f["cx"] < .24 or f["cx"] > .76) and f["w"] <= .22]
    # A visible corner webcam takes precedence over faces in the game/video.
    if corners:
        return "split", max(corners, key=lambda f: f["w"] * f["h"])
    large = [f for f in faces if .20 < f["cx"] < .80 and f["w"] >= .075 and f["h"] >= .14]
    if large:
        return "fullcam", max(large, key=lambda f: f["w"] * f["h"])
    return None, None


def face_crop(faces):
    if not faces:
        return None
    cx, cy, w, h = (median(f[k] for f in faces) for k in ("cx", "cy", "w", "h"))
    x, y = max(0, cx - w), max(0, cy - .9 * h)
    return {"x": x, "y": y, "w": min(1, cx + w) - x, "h": min(1, cy + 1.2 * h) - y}


def timeline_from_samples(samples, duration, step=.5):
    """Require two consecutive detections to switch; bridge brief occlusions.

    Each sample has t and faces. Audio is deliberately not an input.
    A stable crop for each section avoids jitter from individual detections.
    """
    observations = [(s["t"], *classify_faces(s["faces"])) for s in samples]
    decisions = []
    current = None
    pending, pending_start, pending_count = None, 0, 0
    for i, (t, mode, face) in enumerate(observations):
        if mode is None:
            # Looking down or covering one's face is not a scene change.
            pending, pending_count = None, 0
            decisions.append(current)
            continue
        if mode == current:
            pending, pending_count = None, 0
        else:
            if pending != mode:
                pending, pending_start, pending_count = mode, i, 1
            else:
                pending_count += 1
            if pending_count >= 2:
                current = mode
                for j in range(pending_start, len(decisions)):
                    decisions[j] = current
                pending, pending_count = None, 0
        decisions.append(current)
    first = next((d for d in decisions[:2] if d is not None), "portrait")
    decisions = [d or first for d in decisions]
    if not decisions:
        raise RuntimeError("Keine Bilder für die Layout-Erkennung verfügbar.")
    starts = [0] + [i for i in range(1, len(decisions)) if decisions[i] != decisions[i-1]]
    timeline = []
    for n, start in enumerate(starts):
        end = starts[n+1] if n+1 < len(starts) else len(decisions)
        mode = decisions[start]
        faces = [f for _, m, f in observations[start:end] if m == mode and f]
        timeline.append({"start": 0.0 if start == 0 else observations[start][0],
                         "end": observations[end][0] if end < len(observations) else duration,
                         "mode": mode, "face": face_crop(faces)})
    return timeline
