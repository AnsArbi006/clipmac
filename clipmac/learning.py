"""Keep personal editing labels and observed audience signals separate."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from statistics import median

CHECKPOINT_HOURS = (1, 2, 24)
WINDOW_SECONDS = 15 * 60


def sample_ratios(sample):
    """Descriptive ratios, never quality labels or an estimate of unique viewers."""
    views = sample.get("views")
    valid = sample.get("availability") == "public" and isinstance(views, int) and views > 0
    def percent(key):
        value = sample.get(key)
        return round(100 * value / views, 4) if valid and isinstance(value, int) else None
    return {"likes_per_100_views": percent("likes"),
            "comments_per_100_views": percent("comments"),
            "denominator_views": views,
            "interpretation": "descriptive_only_no_quality_label"}


def video_context(job):
    """Archive available local presentation evidence; do not infer historical uploads."""
    result = job.get("result", {})
    folder = Path(result["file"]).parent
    artifacts, missing = {}, []
    for name in ("transcript.json", "captions.ass", "captions.srt"):
        try:
            content = (folder / name).read_text(encoding="utf-8")
            artifacts[name] = json.loads(content) if name.endswith(".json") else content
        except (OSError, ValueError):
            missing.append(name)
    return {"source": "local_files_at_collection_time",
            "matches_published_video": "not_verified",
            "streamer": job.get("clip", {}).get("broadcaster_name"),
            "source_title": job.get("clip", {}).get("title"),
            "metadata": result.get("metadata", {}),
            "render": result.get("render", {}), "edit": result.get("edit", {}),
            "subtitle_words": result.get("subtitle_words"),
            "caption_version": result.get("caption_version"),
            "caption_style": result.get("caption_style"),
            "artifacts": artifacts, "missing_artifacts": missing}


def render_revision(job):
    result = job.get("result", {})
    file = Path(result.get("file", ""))
    stamp = None
    if file.is_file():
        stat = file.stat()
        stamp = [stat.st_size, stat.st_mtime_ns]
    material = {"render": result.get("render"), "edit": result.get("edit"),
                "subtitle_words": result.get("subtitle_words"), "file_stamp": stamp}
    if result.get("caption_version") is not None:
        material.update(caption_version=result["caption_version"], caption_style=result.get("caption_style"))
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def video_statistics(item, channel_id):
    if not item or item.get("snippet", {}).get("channelId") != channel_id:
        return {"availability": "unavailable"}
    public = item.get("status", {}).get("privacyStatus") == "public"
    stats = item.get("statistics", {})
    def count(key):
        value = stats.get(key)
        return int(value) if str(value).isdigit() else None
    values = {"availability": "public" if public else "not_public",
              "views": count("viewCount"), "likes": count("likeCount"), "comments": count("commentCount")}
    values["youtube_metadata"] = {key: item.get("snippet", {}).get(key)
                                  for key in ("title", "description", "tags", "categoryId", "defaultLanguage")}
    try:
        values["published_at"] = datetime.fromisoformat(item["snippet"]["publishedAt"].replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, ValueError):
        pass
    return values


def collect_performance(store, service, channel_id, now, force=False):
    schedules = {r["clip_id"]: r for r in store.performance_sync_rows()}
    jobs = [j for j in store.rows("published") if j["youtube_id"] and j["published"]
            and (force or schedules.get(j["id"], {}).get("next_check", 0) <= now)]
    for start in range(0, len(jobs), 50):
        batch = jobs[start:start+50]
        try:
            response = service.videos().list(part="statistics,snippet,status", id=",".join(j["youtube_id"] for j in batch)).execute()
        except Exception:
            for job in batch:
                store.defer_performance(job["id"], now + 900, "YouTube-Zahlen konnten nicht geladen werden. Neuer Versuch in 15 Minuten.")
            raise
        items = {i["id"]: i for i in response.get("items", [])}
        for job in batch:
            values = video_statistics(items.get(job["youtube_id"]), channel_id)
            store.record_performance(job, values, now, values.get("published_at", job["published"]))
    return len(jobs)


def performance_comparison(clip_id, checkpoints, samples):
    by_id = {s["id"]: s for s in samples}
    mine = [c for c in checkpoints if c["clip_id"] == clip_id and c["state"] == "recorded"]
    if not mine:
        return {"state": "pending", "text": "Vergleich folgt mit passenden Stundenwerten."}
    checkpoint = max(mine, key=lambda c: c["hour"])
    sample = by_id.get(checkpoint["sample_id"])
    peers = [by_id[c["sample_id"]]["views"] for c in checkpoints
             if c["clip_id"] != clip_id and c["hour"] == checkpoint["hour"] and c["state"] == "recorded"
             and c["sample_id"] in by_id and by_id[c["sample_id"]]["views"] is not None]
    if not sample or sample["views"] is None or len(peers) < 5:
        return {"state": "insufficient", "text": "Noch zu wenige vergleichbare Videos.", "peers": len(peers)}
    baseline = median(peers)
    if baseline < 20:
        return {"state": "insufficient", "text": "Noch zu wenig Reichweite für einen sinnvollen Vergleich.", "peers": len(peers)}
    ratio = sample["views"] / baseline
    state = "above" if ratio >= 2 else "below" if ratio < .5 else "typical"
    labels = {"above": "Mehr Aufrufe als im bisherigen Vergleich", "below": "Weniger Aufrufe als im bisherigen Vergleich", "typical": "Aufrufe im bisherigen Vergleichsbereich"}
    return {"state": state, "text": labels[state], "hour": checkpoint["hour"], "peers": len(peers),
            "median_views": baseline, "ratio": round(ratio, 2), "signal": "audience_reach_not_edit_quality"}


def dashboard_learning(store):
    jobs = {j["id"]: j for j in store.rows()}
    ratings = [{k: v for k, v in r.items() if k != "snapshot"} for r in store.rating_rows()]
    for r in ratings:
        r["current_revision"] = r["clip_id"] in jobs and r["revision"] == render_revision(jobs[r["clip_id"]])
    samples, checkpoints = store.performance_rows(), store.checkpoint_rows()
    sync = {r["clip_id"]: r for r in store.performance_sync_rows()}
    performances = {}
    for job in jobs.values():
        if not job["youtube_id"]:
            continue
        mine = [s for s in samples if s["clip_id"] == job["id"]]
        performances[job["id"]] = {"samples": mine, "checkpoints": [c for c in checkpoints if c["clip_id"] == job["id"]],
            "sync": sync.get(job["id"], {}), "comparison": performance_comparison(job["id"], checkpoints, samples)}
    return {"ratings": ratings, "performance": performances, "checkpoint_hours": CHECKPOINT_HOURS,
            "rated_count": sum(r["value"] is not None and r["current_revision"] for r in ratings)}


def learning_export(store):
    samples = [{**s, "ratios": sample_ratios(s)} for s in store.performance_rows()]
    return {"schema_version": 2, "phase": "data_collection_only", "model_trained": False,
            "automatic_model_or_edit_changes": False,
            "notes": "Bewertungen sind subjektive Schnitturteile. YouTube-Zahlen sind beobachtete Zuschauerreaktionen, keine bestätigten Schnittfehler. Fehlende oder verpasste Werte dürfen nicht als null interpretiert werden.",
            "ratio_definitions": {"likes_per_100_views": "100 * likes / views", "comments_per_100_views": "100 * comments / views",
                "limits": "Bei null Aufrufen oder fehlenden Zählern: null. Kleine Nenner sind instabil. Aufrufe sind keine eindeutigen Zuschauer. Unterschiedliche Videoalter nicht als Erfolgsrangliste vergleichen."},
            "video_contexts": store.learning_context_rows(),
            "collection_feedback": store.learning_note_rows(),
            "youtube_metadata_observations": store.youtube_metadata_rows(),
            "ratings_history": store.rating_rows(history=True), "performance_samples": samples,
            "performance_checkpoints": store.checkpoint_rows(), "reports": store.report_rows()}
