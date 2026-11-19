"""Check staged/tracked publication surface, without printing matching secrets."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCKED = {"runtime", "models", "credentials", ".clipmac-dev", "__pycache__", "upstream-tiktok-uploader"}
MEDIA = {".mp4", ".mov", ".wav", ".aiff", ".sqlite", ".db", ".pem", ".key", ".log", ".pyc"}
PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?:ghp_|github_pat_|AIza)[A-Za-z0-9_]{25,}"),
    re.compile(r"ya29\.[A-Za-z0-9_-]{20,}"),
    re.compile(r'''["'](?:access_token|refresh_token|client_secret)["']\s*:\s*["'][^"']{15,}["']'''),
    re.compile(r"/" + "Users" + r"/[^/\s]+/"),
]


def issues(path, content):
    p = Path(path)
    found = []
    if any(part in BLOCKED or part.startswith('.venv') for part in p.parts) or p.suffix.lower() in MEDIA or p.name.startswith('.env'):
        found.append("excluded path/type")
    # Guard's regex literals describe sensitive patterns; still scan its real content.
    if any(pattern.search(content) for pattern in PATTERNS):
        found.append("sensitive pattern")
    return found


def main():
    output = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT)
    failures = []
    count = 0
    for entry in output.decode().split('\0'):
        if not entry:
            continue
        meta, path = entry.split('\t', 1)
        if meta.startswith('160000 '):
            if path != 'upstream-twitch-clipper':
                failures.append((path, 'unexpected submodule'))
            continue
        count += 1
        # Inspect index contents: exactly what the next commit would publish.
        data = subprocess.check_output(["git", "show", f":{path}"], cwd=ROOT)
        for issue in issues(path, data.decode('utf-8', errors='replace')):
            failures.append((path, issue))
    if count == 0:
        raise SystemExit("No tracked files; stage the intended publication first.")
    if failures:
        for path, issue in failures:
            print(f"BLOCKED {path}: {issue}")
        raise SystemExit(1)
    print(f"Publication surface checked: {count} files; no blocked paths or known secret patterns.")


if __name__ == '__main__':
    main()
