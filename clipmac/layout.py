"""Pixel crops for a filled portrait frame, without padding or background copies."""


def fitted_crop(width, height, aspect, center=(0.5, 0.5), minimum=None):
    if minimum:
        crop_w, crop_h = minimum
        crop_w = max(crop_w, crop_h * aspect)
        crop_h = crop_w / aspect
        scale = min(1, width / crop_w, height / crop_h)
        crop_w, crop_h = crop_w * scale, crop_h * scale
    elif width / height > aspect:
        crop_w, crop_h = height * aspect, height
    else:
        crop_w, crop_h = width, width / aspect
    crop_w = max(2, min(width, int(crop_w) // 2 * 2))
    crop_h = max(2, min(height, int(crop_h) // 2 * 2))
    x = max(0, min(width - crop_w, int(center[0] * width - crop_w / 2))) // 2 * 2
    y = max(0, min(height - crop_h, int(center[1] * height - crop_h / 2))) // 2 * 2
    return {"x": x, "y": y, "w": crop_w, "h": crop_h}


def portrait_layout(width, height, face, share=1 / 3, mode=None):
    center = (face["x"] + face["w"] / 2, face["y"] + face["h"] / 2) if face else (0.5, 0.5)
    # A large central face is usually a full-camera shot, not a corner overlay.
    full_camera = face and 0.25 < center[0] < 0.75 and face["h"] > 0.30
    if mode is not None:
        full_camera = mode != "split"
    if not face or full_camera:
        return {"mode": "portrait", "camera_height": 0, "camera": None,
                "content": fitted_crop(width, height, 1080 / 1920, center=center)}
    camera_height = 960 if share == 0.5 else 640
    camera = fitted_crop(width, height, 1080 / camera_height, center,
                         minimum=(face["w"] * width, face["h"] * height))
    content = fitted_crop(width, height, 1080 / (1920 - camera_height))
    return {"mode": "split", "camera_height": camera_height, "camera": camera, "content": content}


def filter_graph(layout):
    def crop(c):
        return f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']}"
    if layout["mode"] == "split":
        h = layout["camera_height"]
        graph = ["[0:v]split=2[camsrc][contentsrc]",
                 f"[camsrc]{crop(layout['camera'])},scale=1080:{h}:flags=lanczos,setsar=1[cam]",
                 f"[contentsrc]{crop(layout['content'])},scale=1080:{1920-h}:flags=lanczos,setsar=1[content]",
                 "[cam][content]vstack=inputs=2[framed]"]
    else:
        graph = [f"[0:v]{crop(layout['content'])},scale=1080:1920:flags=lanczos,setsar=1[framed]"]
    return graph + ["[framed]subtitles=captions.ass[out]"]


def timeline_filter_graph(timeline):
    if len(timeline) == 1:
        return filter_graph(timeline[0]["layout"])
    graph = [f"[0:v]split={len(timeline)}" + "".join(f"[src{i}]" for i in range(len(timeline)))]
    for i, section in enumerate(timeline):
        graph.append(f"[src{i}]trim=start={section['start']:.6f}:end={section['end']:.6f},setpts=PTS-STARTPTS[section{i}]")
        # Prefix all local labels so independently cropped scenes can be joined.
        import re
        for line in filter_graph(section["layout"])[:-1]:
            line = re.sub(r"\[([^]]+)\]", lambda m: f"[section{i}]" if m[1] == "0:v" else f"[s{i}_{m[1]}]", line)
            graph.append(line)
    graph.append("".join(f"[s{i}_framed]" for i in range(len(timeline))) + f"concat=n={len(timeline)}:v=1:a=0[framed]")
    return graph + ["[framed]subtitles=captions.ass[out]"]
