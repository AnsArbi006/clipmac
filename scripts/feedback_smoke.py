"""Compatibility entrypoint: synthetic dashboard, never live data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--ratings" in sys.argv:
    sys.argv.remove("--ratings")
from clipmac.dev import main
if __name__ == "__main__":
    main()
