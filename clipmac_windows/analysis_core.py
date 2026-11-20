"""Portable word timelines and evidence validation shared with the live analysis flow."""

import math
import re

BLOCK_SECONDS = 600
OVERLAP_SECONDS = 30
MAX_SOURCE_SECONDS = 24 * 60 * 60
MAX_CANDIDATES = 12
CRITERIA = ("hook", "context", "payoff")


def blocks(duration):
    if not math.isfinite(duration) or not 1 <= duration <= MAX_SOURCE_SECONDS:
        raise ValueError("Quelle muss zwischen 1 Sekunde und 24 Stunden lang sein.")
    start = 0
    while True:
        end = min(start + BLOCK_SECONDS, duration)
        yield start, end, (start + OVERLAP_SECONDS / 2 if start else 0), (
            end - OVERLAP_SECONDS / 2 if end < duration else duration)
        if end >= duration:
            return
        start += BLOCK_SECONDS - OVERLAP_SECONDS


def absolute_words(transcript, window):
    offset, end, usable_start, usable_end = window
    words = []
    for segment in transcript.get("segments", []):
        for entry in segment.get("words", []):
            try:
                local_a, local_b = float(entry["start"]), float(entry["end"])
                value = entry["word"].strip()[:200]
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
            if not (math.isfinite(local_a) and math.isfinite(local_b)) or not value:
                continue
            start, finish = max(offset, offset + local_a), min(end, offset + local_b)
            if finish > start and usable_start <= (start + finish) / 2 < usable_end:
                words.append({"start": round(start, 3), "end": round(finish, 3), "word": value})
    return words


def deduplicate_words(words):
    result = []
    for word in sorted(words, key=lambda row: (row["start"], row["end"])):
        if word["end"] <= word["start"]:
            continue
        if result:
            previous = result[-1]
            equivalent = re.sub(r"\W", "", previous["word"].casefold()) == re.sub(
                r"\W", "", word["word"].casefold())
            if equivalent and word["start"] < previous["end"]:
                previous["end"] = max(previous["end"], word["end"])
                continue
        result.append(dict(word))
    return result


def utterances(words):
    """Keep observed sentence and pause boundaries, even inside Whisper segments."""
    units = []
    pending = []
    for word in words:
        if pending and (word["start"] - pending[-1]["end"] >= 0.85 or
                        re.search(r"[.!?…][\"'»”]*$", pending[-1]["word"])):
            units.append(pending)
            pending = []
        pending.append(word)
    if pending:
        units.append(pending)
    return [{"start": group[0]["start"], "end": max(word["end"] for word in group),
             "text": " ".join(word["word"] for word in group), "words": group} for group in units]


def windows(units, chat_time=None):
    """Propose contiguous windows around distinct anchors and keep a bounded work list."""
    if not units:
        return []
    if chat_time is not None:
        anchors = [min(range(len(units)), key=lambda i: abs(units[i]["start"] - chat_time))]
    else:
        # Questions and audible reactions seed review windows. They convey no
        # classification of the underlying moment.
        anchors = sorted(range(len(units)),
                         key=lambda i: (not bool(re.search(r"[!?]", units[i]["text"])), i))
    selected = []
    for index in anchors:
        unit = units[index]
        if any(a <= unit["start"] < b for a, b, *_ in selected):
            continue
        left = index
        while left > 0 and unit["start"] - units[left - 1]["start"] <= 20:
            left -= 1
        right = index
        while right + 1 < len(units):
            next_end = units[right + 1]["end"]
            if next_end - units[left]["start"] > 120:
                break
            if (next_end - units[left]["start"] > 60 and
                    units[right]["end"] - units[left]["start"] >= 20):
                break
            if (units[right]["end"] - unit["end"] >= 10 and
                    units[right]["end"] - units[left]["start"] >= 20):
                break
            right += 1
        start, end = units[left]["start"], units[right]["end"]
        if not 0 < end - start <= 120:
            continue
        if any(max(0, min(end, b) - max(start, a)) >= 0.5 * min(end - start, b - a)
               for a, b, *_ in selected):
            continue
        if end - start < 20 and (left > 0 or right < len(units) - 1):
            continue
        selected.append((start, end, units[left:right + 1], index - left))
        if len(selected) >= MAX_CANDIDATES:
            break
    return selected


def _token(text):
    return re.sub(r"\W", "", text.casefold())


def validate_analysis(response, units, anchor):
    """Translate model references to verified source quotes and timestamps."""
    first, last = response.get("first"), response.get("last")
    if (type(first) is not int or type(last) is not int or
            not 0 <= first <= anchor <= last < len(units) or
            not 20 <= units[last]["end"] - units[first]["start"] <= 120):
        return units, {}
    raw = response.get("criteria", {})
    evidence = {}
    reasons = {"hook": "Beleg für den Einstieg", "context": "Beleg für den Zusammenhang",
               "payoff": "Beleg für Höhepunkt oder Abschluss"}
    if isinstance(raw, dict):
        for key in CRITERIA:
            item = raw.get(key)
            if not isinstance(item, dict):
                continue
            value, quote = item.get("value"), item.get("quote")
            if type(value) is not int or value not in (0, 1, 2):
                continue
            if not isinstance(quote, str) or not 1 <= len(quote.strip()) <= 1000:
                continue
            # The quote must occur verbatim (ignoring case/punctuation) inside the chosen span.
            # Small models cite across sentences or with a wrong unit number: search the whole
            # span and accept the longest verbatim prefix of at least min(3, quote length) words.
            source_words = [w for unit in units[first:last + 1] for w in unit["words"]]
            norm = [_token(w["word"]) for w in source_words]
            quote_words = [t for t in (_token(q) for q in quote.split()) if t]
            need = min(3, len(quote_words))
            best = None
            for i in range(len(norm)):
                n = 0
                while n < len(quote_words) and i + n < len(norm) and norm[i + n] == quote_words[n]:
                    n += 1
                if n >= need and n and (best is None or n > best[1]):
                    best = (i, n)
            if best:
                span = source_words[best[0]:best[0] + best[1]]
                evidence[key] = {"value": value, "start": span[0]["start"], "end": span[-1]["end"],
                                 "quote": " ".join(word["word"] for word in span), "reason": reasons[key]}
    return units[first:last + 1], evidence


def interior_intervals(duration, words, quiet):
    """Compact silence contained between words, while retaining its context."""
    gaps = []
    previous_end = None
    for word in words:
        if previous_end is not None and word["start"] > previous_end:
            gaps.append((previous_end, word["start"]))
        previous_end = max(previous_end or 0, word["end"])
    # Keep the 20-second lower length goal and limit the effect on pacing.
    budget, cursor = max(0, min(duration - 20, duration * 0.15)), 0.0
    keep = []
    for start, end in quiet:
        if end - start < 3 - 0.0001 or not any(a <= start and end <= b for a, b in gaps):
            continue
        removed = min(2.0, budget, end - start - 1.6)
        if removed < 0.2:
            break
        middle = (start + end) / 2
        keep.append((cursor, round(middle - removed / 2, 6)))
        cursor = round(middle + removed / 2, 6)
        budget -= removed
    keep.append((cursor, duration))
    return keep


def remap_words(words, intervals):
    """Map word timestamps to a nonreordered timeline with whole words retained."""
    result, elapsed = [], 0.0
    for start, end in intervals:
        for word in words:
            if start <= word["start"] < word["end"] <= end:
                result.append({**word, "start": round(elapsed + word["start"] - start, 3),
                               "end": round(elapsed + word["end"] - start, 3)})
        elapsed += end - start
    if len(result) != len(words):
        raise ValueError("Ein Schnitt würde ein gesprochenes Wort verkürzen.")
    return result
