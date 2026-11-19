"""Process-wide data location and development isolation; set before imports."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVELOPMENT = os.environ.get("CLIPMAC_DEV") == "1"
RUNTIME = Path(os.environ.get("CLIPMAC_DATA_DIR") or
               ROOT / (".clipmac-dev" if DEVELOPMENT else "runtime")).expanduser().resolve()

if DEVELOPMENT:
    # Never adopt an existing live data directory, even when explicitly supplied.
    marker = RUNTIME / ".clipmac-development"
    if RUNTIME == (ROOT / "runtime").resolve():
        raise RuntimeError("Der Entwicklungsmodus darf runtime/ nicht verwenden.")
    if RUNTIME.exists() and any(RUNTIME.iterdir()) and not marker.is_file():
        raise RuntimeError("Entwicklungsdaten brauchen ein leeres oder markiertes Verzeichnis.")
    if (RUNTIME / "credentials").exists():
        raise RuntimeError("Im Entwicklungsverzeichnis dürfen keine Zugangsdaten liegen.")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)


def require_live(action):
    if DEVELOPMENT:
        raise RuntimeError(f"Entwicklungsmodus: {action} ist gesperrt.")
