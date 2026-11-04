"""Where the voice bridge keeps its bulky files. Edit storage.json (or run storage.ps1 -MoveCache/-MoveModels).

storage.json  (paths may be absolute or relative to this folder; missing file = defaults)
    {"cache_dir": ".cache", "models_dir": "models", "keep_logs_days": 14}

cache_dir   disposable: pip downloads, temp audio, window (WebView2) data, Hugging Face metadata.
            Safe to delete any time (the bridge recreates it). Clear it with storage.ps1 -Clean or the window's
            Settings > "Clear cache".
models_dir  the voice + speech models (hundreds of MB each). Put it on whichever drive has room.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULTS = {"cache_dir": ".cache", "models_dir": "models", "keep_logs_days": 14}


def _load() -> dict:
    try:
        return {**DEFAULTS, **json.loads((HERE / "storage.json").read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULTS)


def _resolve(p: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(p)))
    return (p if p.is_absolute() else HERE / p).resolve()


CFG = _load()
CACHE = _resolve(CFG["cache_dir"])
MODELS = _resolve(CFG["models_dir"])
LOGS = HERE / "logs"


def apply_env():
    """Point every cache/temp at CACHE (never the C: profile). Call before importing heavy libs."""
    for d in ("tmp", "hf", "pip", "webview"):
        (CACHE / d).mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(CACHE / "tmp")
    os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
    os.environ.setdefault("PIP_CACHE_DIR", str(CACHE / "pip"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def size_mb(p: Path) -> float:
    """Folder size; files reached through several links (HF snapshots -> blobs) count once."""
    if not p.exists():
        return 0.0
    if p.is_file():
        return p.stat().st_size / 1e6
    seen, total = set(), 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                r = f.resolve()
                if r not in seen:
                    seen.add(r)
                    total += r.stat().st_size
        except OSError:
            pass
    return total / 1e6


def report() -> dict:
    parts = {
        "cache (disposable)": CACHE,
        "models": MODELS,
        "python packages (.venv)": HERE / ".venv",
        "logs": LOGS,
    }
    out = {k: {"path": str(v), "mb": round(size_mb(v), 1)} for k, v in parts.items()}
    out["cache breakdown"] = {d.name: round(size_mb(d), 1) for d in sorted(CACHE.iterdir())} if CACHE.exists() else {}
    try:
        out["free_gb"] = {"cache drive": round(shutil.disk_usage(CACHE).free / 1e9, 1),
                          "models drive": round(shutil.disk_usage(MODELS).free / 1e9, 1)}
    except OSError:
        pass
    return out


def clear_cache(include_webview: bool = False) -> float:
    """Delete disposable files. Returns MB freed. webview is skipped while the window may be open."""
    freed = 0.0
    for name in ("pip", "tmp", "hf") + (("webview",) if include_webview else ()):
        d = CACHE / name
        if not d.exists():
            continue
        for child in list(d.iterdir()):
            mb = size_mb(child)
            try:
                shutil.rmtree(child) if child.is_dir() else child.unlink()
                freed += mb
            except OSError:
                pass  # in use (e.g. the audio file being played) - skip
    return round(freed, 1)


def prune_logs(days: int | None = None) -> int:
    """Remove dated transcripts older than `days`; trim feed.log to its last ~2 MB. Returns files removed."""
    days = CFG["keep_logs_days"] if days is None else days
    removed, cutoff = 0, time.time() - days * 86400
    if LOGS.exists():
        for f in LOGS.glob("voice_*.md"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                removed += 1
        feed = LOGS / "feed.log"
        if feed.exists() and feed.stat().st_size > 5_000_000:
            tail = feed.read_bytes()[-2_000_000:]
            feed.write_bytes(tail[tail.find(b"\n") + 1:])
    return removed


if __name__ == "__main__":
    import sys
    if "--clean" in sys.argv:
        print(f"freed {clear_cache(include_webview='--all' in sys.argv)} MB, removed {prune_logs()} old logs")
    print(json.dumps(report(), indent=2))
