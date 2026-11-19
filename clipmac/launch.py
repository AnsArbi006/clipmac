import os
import subprocess
import sys
import time
import webbrowser
from urllib.request import urlopen

from .state import ROOT, RUNTIME
from .environment import DEVELOPMENT


def reachable(url):
    try:
        with urlopen(url, timeout=2):
            return True
    except Exception:
        return False


def main():
    if DEVELOPMENT:
        raise RuntimeError("Entwicklungsmodus: mit python -m clipmac.dev starten.")
    if reachable("http://127.0.0.1:8768/api/state"):
        webbrowser.open("http://127.0.0.1:8768")
        return
    RUNTIME.mkdir(exist_ok=True)
    if not reachable("http://127.0.0.1:11435/api/tags"):
        env = {**os.environ, "OLLAMA_HOST": "127.0.0.1:11435", "OLLAMA_MODELS": str(ROOT / "models" / "ollama"), "OLLAMA_NO_CLOUD": "1"}
        with (RUNTIME / "ollama.log").open("a") as log:
            subprocess.Popen(["/opt/homebrew/bin/ollama", "serve"], env=env, stdout=log, stderr=log, start_new_session=True)
        for _ in range(40):
            if reachable("http://127.0.0.1:11435/api/tags"):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Lokale KI konnte nicht starten. Siehe runtime/ollama.log.")
    import threading
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8768")).start()
    from .server import serve
    serve()


if __name__ == "__main__":
    main()
