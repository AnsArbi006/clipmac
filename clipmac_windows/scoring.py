"""Viral Score (experimentell) and the conservative v1 publication gate.

The score is an editorial aid on a 0-100 scale, not a success probability.
Weights and thresholds are fixed starting values; nothing here is trained.
"""

import math

VERSION = "cm012-windows-score-v1"
DEFAULT_THRESHOLD = 70
WEIGHTS = {"chat_strength": 20, "participants": 15, "hook": 20, "context": 20, "payoff": 25}
TEXT = ("hook", "context", "payoff")
LABELS = {"chat_strength": "Chat-Stärke", "participants": "Teilnehmerbreite", "hook": "Einstieg",
          "context": "Kontext", "payoff": "Höhepunkt/Abschluss"}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def chat_component(observed, baseline):
    """Relative to the channel's own baseline: 1x -> 0, 5x -> 100, linear and clamped."""
    if not _finite(observed) or not _finite(baseline) or observed < 0 or baseline < 0:
        return None
    ratio = observed / max(1.0, baseline)
    return round(min(100.0, max(0.0, (ratio - 1) * 25)), 2)


def score(chat, evidence):
    """Return (score or None, components). Any missing signal yields None."""
    components = {}
    if isinstance(chat, dict):
        components["chat_strength"] = chat_component(chat.get("messages"), chat.get("baseline_messages"))
        components["participants"] = chat_component(chat.get("participants"), chat.get("baseline_participants"))
    else:
        components["chat_strength"] = components["participants"] = None
    evidence = evidence if isinstance(evidence, dict) else {}
    for key in TEXT:
        item = evidence.get(key)
        value = item.get("value") if isinstance(item, dict) else None
        components[key] = value * 50 if type(value) is int and value in (0, 1, 2) else None
    if any(value is None for value in components.values()):
        return None, components
    total = sum(components[key] * weight for key, weight in WEIGHTS.items()) / sum(WEIGHTS.values())
    return round(total, 1), components


def decide(*, chat, evidence, category_ok, coverage_ok, technical_errors, threshold=DEFAULT_THRESHOLD,
           duration=None):
    """All conditions of the v1 gate must hold. Return a persisted, versioned decision."""
    if type(threshold) is not int or not 0 <= threshold <= 100:
        raise ValueError("Die Score-Schwelle muss eine ganze Zahl von 0 bis 100 sein.")
    value, components = score(chat, evidence)
    reasons = []
    if not isinstance(chat, dict) or not chat.get("messages"):
        reasons.append("Keine bestätigte Chat-Spitze.")
    if value is None:
        missing = [LABELS[key] for key, item in components.items() if item is None]
        reasons.append("Fehlende Signale: " + ", ".join(missing) + ".")
    elif value < threshold:
        reasons.append(f"Score {value} unter Schwelle {threshold}.")
    for key in ("context", "payoff"):
        item = (evidence or {}).get(key)
        if not isinstance(item, dict) or item.get("value", 0) < 1:
            reasons.append(f"{LABELS[key]} nicht mindestens 1/2 belegt.")
    if not category_ok:
        reasons.append("Kategorie unbekannt, gemischt oder nicht passend.")
    if not coverage_ok:
        reasons.append("Aufnahme unvollständig oder Kontext fehlt.")
    if duration is not None and not 20 <= duration <= 120:
        reasons.append("Schnittlänge außerhalb 20-120 Sekunden.")
    reasons.extend(technical_errors or [])
    return {"label": "Viral Score (experimentell)", "version": VERSION, "score": value,
            "components": components, "threshold": threshold, "eligible": not reasons,
            "reasons": reasons}
