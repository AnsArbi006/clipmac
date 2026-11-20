"""Windows-only data location, settings and process lock."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

REPO = Path(__file__).resolve().parent.parent
PROFILE = REPO / 'examples' / 'settings.gta6.json'
PLATFORMS = ('tiktok', 'youtube')


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as out:
        temporary = Path(out.name)
        json.dump(data, out, ensure_ascii=False, allow_nan=False)
        out.flush()
        os.fsync(out.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def data_root(raw, demo):
    if raw is None:
        local = os.environ.get('LOCALAPPDATA')
        if not local:
            raise ValueError('Bitte einen separaten Ordner mit --data-dir angeben.')
        raw = Path(local) / ('ClipMacWindowsDemo' if demo else 'ClipMacWindows')
    root = Path(raw).expanduser().resolve()
    if root in {REPO, Path(root.anchor)} or root.is_relative_to(REPO / 'runtime'):
        raise ValueError('Bitte einen eigenen Windows-Datenordner angeben.')
    marker = root / '.clipmac-windows'
    mode = 'demo' if demo else 'live'
    root.mkdir(parents=True, exist_ok=True)
    if marker.exists():
        if marker.is_symlink() or marker.read_text(encoding='utf-8').strip() != mode:
            raise ValueError('Demo und Livebetrieb brauchen getrennte Datenordner.')
    elif any(root.iterdir()):
        raise ValueError('Bitte einen leeren oder bereits markierten Windows-Datenordner wählen.')
    else:
        try:
            with marker.open('x', encoding='utf-8') as file:
                file.write(mode + '\n')
        except FileExistsError as exc:
            raise ValueError('Der Datenordner wird bereits eingerichtet.') from exc
    return root


def settings(root):
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    disk = root / 'settings.json'
    options = json.loads(disk.read_text(encoding='utf-8')) if disk.exists() else {}
    threshold = options.get('score_threshold', 70)
    if type(threshold) is not int or not 0 <= threshold <= 100:
        raise ValueError('Die Score-Schwelle muss eine ganze Zahl von 0 bis 100 sein.')
    return {**options, 'score_threshold': threshold,
            'streamers': profile['streamers'], 'required_game_id': profile['required_game_id'],
            'required_game_name': profile['required_game_name'],
            'whisper_model_path': str(root / 'models' / 'whisper-small'),
            'face_model_path': str(root / 'models' / 'face_detection_yunet_2023mar.onnx'),
            'ollama_model': options.get('ollama_model', 'qwen2.5:3b')}


@contextmanager
def process_lock(root):
    import msvcrt

    with (root / 'process.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'\0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('Für diesen Datenordner läuft bereits eine Windows-Instanz.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
