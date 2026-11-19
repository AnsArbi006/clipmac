"""Fail-closed category and freshness gates for discovery and publication."""
from datetime import datetime, timedelta, timezone


def rejection_reason(clip, cfg, now=None):
    if not cfg.get("required_game_id"):
        return "Spielkategorie noch nicht bestätigt." if cfg.get("required_game_name") else ""
    if str(clip.get("game_id", "")) != cfg["required_game_id"]:
        return "Nicht in der freigegebenen Twitch-Spielkategorie."
    if clip.get("streamer_login", "").lower() not in cfg["streamers"]:
        return "Streamer nicht mehr freigegeben."
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(clip["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("missing timezone")
    except (KeyError, ValueError, TypeError, AttributeError):
        return "Clip-Alter nicht verifizierbar."
    if not now - timedelta(hours=cfg["lookback_hours"]) <= created <= now:
        return "Clip liegt außerhalb des aktuellen Zeitfensters."
    return ""


def ranked_pool(clips, cfg, limit, now=None):
    eligible = [c for c in clips if not rejection_reason(c, cfg, now)]
    ranked = sorted(eligible, key=lambda c: (-int(c.get("view_count", 0)), c["id"]))
    if cfg.get("selection_scope", "per_streamer") == "global":
        return ranked[:limit]
    counts, selected = {}, []
    for clip in ranked:
        login = clip["streamer_login"]
        if counts.get(login, 0) < limit:
            selected.append(clip)
            counts[login] = counts.get(login, 0) + 1
    return selected
