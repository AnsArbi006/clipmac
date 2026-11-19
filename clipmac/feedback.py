"""Local evidence for user reports. No model training or automatic code changes."""
import hashlib
import json

from .state import ROOT, atomic_json
from .media import binary, probe, run


def original_time(edited_time, intervals):
    cursor = 0.0
    for start, end in intervals:
        length = end - start
        if edited_time < cursor + length:
            return start + edited_time - cursor
        cursor += length
    if intervals and abs(edited_time - cursor) < .05:
        return intervals[-1][1]
    return None


def diagnose(note, result, position, source_width=None):
    text = note.casefold()
    camera = any(w in text for w in ("kamera", "facecam", "fullcam", "gameplay", "zoom", "ausschnitt"))
    subtitles = any(w in text for w in ("untertitel", "wort", "wörter", "geschrieben"))
    category = "camera" if camera else "subtitles" if subtitles else "editing"
    render = result.get("render", {})
    timeline = render.get("timeline", [])
    if not timeline and render.get("layout"):
        timeline = [{"start": 0, "end": render.get("duration", 0), "mode": render["layout"]["mode"], "layout": render["layout"]}]
    section = next((s for s in timeline if s["start"] <= position < s["end"]), None)
    facts = []
    if section:
        layout = section.get("layout", {})
        mode = layout.get("mode", section["mode"])
        facts.append("An der Vergleichsstelle wurde " + ("Facecam über Hauptinhalt" if mode == "split" else "ein einzelner Hochformat-Ausschnitt") + " gerendert.")
        if section["mode"] == "portrait" and not section.get("face"):
            facts.append("Die gespeicherte Erkennung enthält für diesen Abschnitt keine Facecam.")
        crop = layout.get("content", {})
        if source_width and crop.get("w"):
            facts.append(f"Der Hauptausschnitt zeigt {round(crop['w'] / source_width * 100)} % der ursprünglichen Bildbreite.")
    else:
        facts.append("Für diese Stelle liegen noch keine gespeicherten Layoutdaten vor.")
    if camera:
        hypothesis = "Mögliche Ursache: Kamera übersehen, falscher Szenentyp oder zu enger Ausschnitt. Erst im Originalbild prüfen; ein Gameplay-Gesicht darf nicht als Streamer-Kamera übernommen werden."
        checks = ["Position und Größe der tatsächlichen Streamer-Kamera im Original festhalten.",
                  "An der gemeldeten Stelle erwartetes Layout und gewünschten Ausschnitt bestätigen.",
                  "Korrigierte Vorschau mit dem Original vergleichen: Gesicht vollständig, relevanter Hauptinhalt sichtbar.",
                  "Bisher gute Split- und Fullcam-Beispiele nach der Änderung erneut prüfen."]
        components = ["clipmac/facecam.py", "clipmac/scenes.py", "clipmac/layout.py"]
    elif subtitles:
        hypothesis = "Mögliche Ursache: Spracherkennung, Schreibweise oder Untertitel-Timing. Den gesprochenen Wortlaut anhand der Tonspur prüfen."
        checks = ["Tatsächlichen Wortlaut und Zeitbereich festhalten.", "Untertitel nach der Korrektur mit der Tonspur vergleichen.", "Korrektur darf andere Wörter und Zeitmarken nicht verändern."]
        components = ["clipmac/media.py:transcribe", "clipmac/media.py:write_subtitles"]
    else:
        hypothesis = "Ursache noch offen. Original und Ergebnis am gemeldeten Zeitpunkt vergleichen; insbesondere Schnittgrenzen und Ton prüfen."
        checks = ["Gewünschtes Verhalten an der gemeldeten Stelle festhalten.", "Korrektur am Original und der neuen Vorschau überprüfen.", "Bisher gute Vergleichsclips erneut prüfen."]
        components = ["clipmac/media.py"]
    return {"category": category, "facts": facts, "hypothesis": hypothesis,
            "checks": checks, "components": components, "sample_time": position,
            "diagnosis_confirmed": False, "correction_applied": False}


def prepare_case(report, runtime):
    directory = runtime / "feedback" / report["id"]
    directory.mkdir(parents=True, exist_ok=True)
    clip_dir = runtime / "clips" / report["clip_id"]
    result = report["snapshot"]["result"]
    # If the report arrived during editing, gather its first completed render.
    if not result.get("render") and (clip_dir / "result.json").is_file():
        result = json.loads((clip_dir / "result.json").read_text())
    output, source = clip_dir / "final.mp4", clip_dir / "source.mp4"
    duration = result.get("render", {}).get("duration", 0)
    position = report["position"] if report["position"] is not None else min(3.0, duration / 2)
    source_meta = probe(source) if source.is_file() else None
    width = next((s["width"] for s in source_meta["streams"] if s["codec_type"] == "video"), None) if source_meta else None
    analysis = diagnose(report["note"], result, position, width)
    analysis["time_selected_by_user"] = report["position"] is not None
    analysis["frames"] = []
    analysis["evidence_notes"] = []
    intervals = result.get("edit", {}).get("kept_intervals", [])
    if output.is_file() and duration:
        times = sorted({round(max(0, min(duration - .05, position + delta)), 3) for delta in (-1, 0, 1)})
        for i, t in enumerate(times):
            source_t = original_time(t, intervals)
            pair = {"output_time": t, "source_time": source_t}
            for label, path, at in (("output", output, t), ("source", source, source_t)):
                if at is None or not path.is_file():
                    continue
                name = f"{label}-{i}.jpg"
                try:
                    run([binary("ffmpeg"), "-v", "error", "-nostdin", "-y", "-ss", at, "-i", path,
                         "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", directory / name], timeout=30)
                    if (directory / name).is_file():
                        pair[label] = f"/feedback/{report['id']}/{name}"
                except Exception:
                    analysis["evidence_notes"].append(f"Vergleichsbild {label} bei {t} Sekunden konnte nicht erstellt werden.")
            analysis["frames"].append(pair)
    else:
        analysis["evidence_notes"].append("Noch keine fertige Videodatei vorhanden; Prüffall enthält zunächst die Meldung und verfügbaren Schnittdaten.")
    if not intervals:
        analysis["evidence_notes"].append("Keine Schnitt-Zuordnung gespeichert; Original-Zeitpunkt muss bei der Analyse manuell geprüft werden.")
    code_hashes = {name: hashlib.sha256((ROOT / "clipmac" / name).read_bytes()).hexdigest()
                   for name in ("facecam.py", "scenes.py", "layout.py", "media.py")}
    case = {"schema_version": 1, "id": report["id"], "clip_id": report["clip_id"],
            "reported_at": report["created"], "user_report": report["note"],
            "position": report["position"], "snapshot": report["snapshot"],
            "examined_result": result, "analysis": analysis, "code_hashes": code_hashes,
            "regression": {"status": "needs_review", "expected_behavior": None,
                           "checks": analysis["checks"], "verified_at": None}}
    atomic_json(directory / "case.json", case)
    return analysis
