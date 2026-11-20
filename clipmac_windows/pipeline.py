"""Candidate -> transcript -> evidence -> cut -> checks -> score. One worker runs this serially."""

import json
from pathlib import Path

from . import analysis_core as core
from . import render, scoring
from .llm import PROMPT_VERSION, ask_ollama
from .live_capture import binary

_whisper = {}


def whisper_transcribe(source, cfg, cancel):
    """Local faster-whisper with word times, in 10-minute blocks with 30 s overlap."""
    from faster_whisper import WhisperModel
    path = cfg["whisper_model_path"]
    if path not in _whisper:
        if not Path(path).is_dir():
            raise RuntimeError("Whisper-Modell fehlt. Siehe docs/WINDOWS.md, Abschnitt Modelle.")
        _whisper.clear()
        _whisper[path] = WhisperModel(path, device="cpu", compute_type="int8", local_files_only=True)
    model = _whisper[path]
    duration = float(render.probe(source)["format"]["duration"])
    words = []
    folder = Path(source).parent
    for window in core.blocks(duration):
        start, end = window[0], window[1]
        audio = folder / f"block-{int(start)}.wav"
        render.run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-ss", str(start), "-i", source,
                    "-t", str(end - start), "-map", "0:a:0", "-ac", "1", "-ar", "16000", audio], cancel)
        segments, _ = model.transcribe(str(audio), language=cfg.get("language", "de"), vad_filter=True,
                                       word_timestamps=True, condition_on_previous_text=False)
        transcript = {"segments": [{"words": [{"start": w.start, "end": w.end, "word": w.word}
                                              for w in (s.words or [])]}
                                   for s in segments if s.no_speech_prob < 0.8]}
        words.extend(core.absolute_words(transcript, window))
        audio.unlink(missing_ok=True)
        if cancel.is_set():
            raise render.Cancelled()
    return core.deduplicate_words(words)


def ollama_ask(units, anchor, cfg, **_):
    return ask_ollama(units, anchor, cfg["ollama_model"])


def metadata(channel, cfg):
    game = cfg.get("required_game_name") or "Twitch"
    title = f"{channel} – {game} Highlight"
    return {"title": title[:95], "description": f"Live-Highlight von twitch.tv/{channel}\n#gta6 #twitch #{channel}",
            "tags": ["gta6", "twitch", channel]}


def process(candidate, source, folder, cfg, *, transcribe=whisper_transcribe, ask=ollama_ask, cancel):
    """Return a JSON-safe result. Never raise for a weak clip; only for cancellation/IO faults."""
    folder = Path(folder)
    chat = candidate.get("chat")
    chat_time = candidate["trigger"] - candidate["start"]
    category_ok = not candidate.get("category_review", True) and not candidate.get("category_pending")
    result = {"channel": candidate["channel"], "trigger": candidate["trigger"], "chat": chat,
              "category": candidate.get("category_name") or None, "prompt_version": PROMPT_VERSION,
              "model": cfg.get("ollama_model"), "metadata": metadata(candidate["channel"], cfg)}
    words = transcribe(source, cfg, cancel)
    units = core.utterances(words)
    proposals = core.windows(units, chat_time)
    if not proposals:
        result["decision"] = scoring.decide(chat=chat, evidence={}, category_ok=category_ok, coverage_ok=True,
                                            technical_errors=["Keine Sprache im Ausschnitt erkannt."],
                                            threshold=cfg["score_threshold"])
        result.update(score=None, eligible=False, reason=result["decision"]["reasons"][0])
        return result
    _, _, window_units, relative_anchor = proposals[0]
    evidence, model_error = {}, None
    try:
        # The model rates only the pre-selected window; small local models pick ranges poorly.
        response = ask(window_units, relative_anchor, cfg)
        response = dict(response) if isinstance(response, dict) else {}
        first, last = response.get("first"), response.get("last")
        if (type(first) is not int or type(last) is not int
                or not 0 <= first <= relative_anchor <= last < len(window_units)
                or not 20 <= window_units[last]["end"] - window_units[first]["start"] <= 120):
            response.update(first=0, last=len(window_units) - 1)
        chosen, evidence = core.validate_analysis(response, window_units, relative_anchor)
        if not evidence:
            chosen = window_units
    except render.Cancelled:
        raise
    except Exception as exc:  # local model down, timeout or invalid JSON: never a release
        model_error = f"Lokale KI-Analyse fehlgeschlagen: {type(exc).__name__}."
        chosen = window_units
    start = max(0.0, chosen[0]["start"] - 0.25)
    end = chosen[-1]["end"] + 0.4
    if end - start > 120:
        end = start + 120
    edit = render.edit(source, start, end, words, folder, cfg, candidate["channel"], cancel)
    errors = list(edit["technical_errors"])
    if model_error:
        errors.append(model_error)
    decision = scoring.decide(chat=chat, evidence=evidence, category_ok=category_ok, coverage_ok=True,
                              technical_errors=errors, threshold=cfg["score_threshold"],
                              duration=edit["duration"])
    result.update(edit=edit, evidence=evidence, decision=decision, score=decision["score"],
                  eligible=decision["eligible"], duration=edit["duration"],
                  reason="Geeignet" if decision["eligible"] else decision["reasons"][0])
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
