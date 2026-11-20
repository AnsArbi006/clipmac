"""Optional synthetic dashboard preview using the existing test-tone video."""

import hashlib
import shutil
import time

from .environment import DEVELOPMENT
from .state import atomic_json


def seed_preview(runtime):
    if not DEVELOPMENT:
        raise RuntimeError("Highlight-Beispiele brauchen den isolierten Entwicklungsmodus.")
    source = runtime / "clips" / "synthetic-1" / "final.mp4"
    if not source.is_file():
        return
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    item_id = hashlib.sha256(("highlight-demo:" + digest).encode()).hexdigest()[:32]
    folder = runtime / "highlight-analysis" / "candidates" / item_id
    if (folder / "candidate.json").exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "final.mp4"
    shutil.copyfile(source, target)
    words = [{"start": 0.2, "end": 0.6, "word": "Test"},
             {"start": 0.7, "end": 1.0, "word": "mit"},
             {"start": 1.1, "end": 1.6, "word": "Testton."}]
    atomic_json(folder / "candidate.json", {
        "id": item_id, "kind": "local", "created": time.time(), "source_id": digest,
        "source_media_sha256": digest, "start": 0, "end": 4, "words": words, "channel": "Synthetisches Beispiel",
        "evidence": {"hook": {"value": 1, "start": 0.2, "end": 1.6, "quote": "Test mit Testton.",
                              "reason": "Erfundener Beleg zur Ansicht der Karte."}},
        "review_required": True, "preview_ready": True, "render_revision": digest,
        "result": {"file": str(target), "render": {"duration": 4}},
        "model": "Synthetische Vorschau", "prompt_version": "fixture-v1",
    })
