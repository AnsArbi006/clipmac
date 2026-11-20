"""Versioned editorial estimates from within-source chat and transcript evidence."""

from __future__ import annotations

import math
import re
import unicodedata

VERSION = "cm012-score-v1"
DEFAULT_THRESHOLD = 60
TEXT_WEIGHTS = {"hook": 20, "context": 20, "payoff": 25}
CHAT_WEIGHTS = {"chat_strength": 20, "participants": 15}
LABELS = {"hook": "Einstieg", "context": "Verständlicher Kontext", "payoff": "Höhepunkt und Abschluss",
          "chat_strength": "Chat-Spitze", "participants": "Teilnehmerbreite"}


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _tokens(text):
    if not isinstance(text, str):
        return []
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def _evidence(item, words, start, end):
    if not isinstance(item, dict) or not finite(start) or not finite(end):
        return None
    value, a, b = item.get("value"), item.get("start"), item.get("end")
    quote, reason = item.get("quote"), item.get("reason")
    if (type(value) is not int or value not in (0, 1, 2) or
            not finite(a) or not finite(b) or not start <= a < b <= end or
            not isinstance(quote, str) or not 1 <= len(quote) <= 400 or
            not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500):
        return None
    cited = _tokens(quote)
    transcript = []
    for word in words:
        if not isinstance(word, dict):
            continue
        wa, wb = word.get("start"), word.get("end")
        if finite(wa) and finite(wb) and wa < wb and wa < b and wb > a:
            transcript.extend(_tokens(word.get("word")))
    if not cited or not any(transcript[i:i + len(cited)] == cited for i in range(len(transcript))):
        return None
    return {"value": value, "start": a, "end": b, "quote": quote, "reason": reason.strip()}


def _chat_component(chat, observed, baseline):
    amount = chat.get(observed)
    normal = chat.get(baseline)
    if not finite(amount) or not finite(normal) or amount < 0 or normal < 0:
        return None
    ratio = amount / max(1.0, normal)
    return {"score": round(min(100.0, max(0.0, (ratio - 1) * 25)), 4),
            "ratio": round(ratio, 4), "observed": amount, "baseline": normal,
            "reason": f"{ratio:.2f}× der historischen Basis dieses Kanals"}


def score_highlight(candidate, threshold=DEFAULT_THRESHOLD):
    """Return an unranked result unless all expected components have evidence."""
    if not finite(threshold) or not 0 <= threshold <= 100:
        raise ValueError("Die Empfehlungsschwelle muss zwischen 0 und 100 liegen.")
    source_evidence = candidate.get("evidence")
    words = candidate.get("words")
    source_evidence = source_evidence if isinstance(source_evidence, dict) else {}
    words = words if isinstance(words, (list, tuple)) else []
    chat = candidate.get("live_context")
    chat = chat.get("chat") if isinstance(chat, dict) else None
    weights = {**CHAT_WEIGHTS, **TEXT_WEIGHTS} if chat is not None else TEXT_WEIGHTS
    components = {}
    for key, weight in weights.items():
        if key in TEXT_WEIGHTS:
            item = _evidence(source_evidence.get(key), words, candidate.get("start"), candidate.get("end"))
            value = ({"score": item["value"] * 50, "reason": item["reason"], "evidence": item}
                     if item is not None else None)
        elif isinstance(chat, dict) and key == "chat_strength":
            value = _chat_component(chat, "messages", "baseline_messages")
        elif isinstance(chat, dict):
            value = _chat_component(chat, "participants", "baseline_participants")
        else:
            value = None
        components[key] = {"label": LABELS[key], "weight": weight,
                           "effective_weight": round(100 * weight / sum(weights.values()), 4),
                           **(value or {"score": None, "reason": "Kein belastbarer Beleg vorhanden."})}
    missing = [item["label"] for item in components.values() if item["score"] is None]
    score = None if missing else round(sum(components[k]["score"] * w for k, w in weights.items()) / sum(weights.values()), 2)
    reasons = [f"Kein Gesamtwert ohne Belege für {', '.join(missing)}."] if missing else []
    if chat is None:
        reasons.append("Ohne Chat, nur mit anderen Textwertungen vergleichbar.")
    blocked = bool(candidate.get("technical_errors") or candidate.get("technical_blocked"))
    if blocked:
        reasons.append("Technischer Fehler. Der Schnitt ist für die Freigabe gesperrt.")
    return {"label": "Viral Score (experimentell)", "score": score, "mode": "text" if chat is None else "live",
            "version": VERSION, "model": candidate.get("model"), "prompt_version": candidate.get("prompt_version"),
            "threshold": threshold, "eligible": not blocked and score is not None,
            "recommended": not blocked and score is not None and score >= threshold,
            "components": components, "reasons": reasons}
