"""
ELİŞA Settings Persistence
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Thread-safe user settings that persist to ~/.config/elisha/settings.yaml
Separate from config.yaml (which is project-level / read-only defaults).
"""
import threading
from pathlib import Path
import yaml

_SETTINGS_DIR = Path.home() / ".config" / "elisha"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.yaml"

_DEFAULTS = {
    "tts_enabled": True,
    "wake_enabled": False,
    "provider": "auto",       # local / cloud / auto
    "voice": "tr_TR-dfki-medium",
    "speed": 1.0,
    "volume": 0.8,
    "theme": "dark",
}

_lock = threading.Lock()
_cache = None  # type: dict | None


def _load() -> dict:
    """Load settings from disk (or return defaults)."""
    global _cache
    if _cache is not None:
        return _cache
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
    else:
        data = {}
    # Merge with defaults (missing keys get default values)
    merged = {**_DEFAULTS, **data}
    _cache = merged
    return _cache


def _save():
    """Write current cache to disk."""
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(_cache, f, allow_unicode=True, default_flow_style=False)


def get(key: str, default=None):
    """Get a setting value. Thread-safe."""
    with _lock:
        store = _load()
        return store.get(key, default if default is not None else _DEFAULTS.get(key))


def set(key: str, value):
    """Set a setting value and persist immediately. Thread-safe."""
    with _lock:
        store = _load()
        store[key] = value
        _save()


def get_all() -> dict:
    """Return a copy of all settings. Thread-safe."""
    with _lock:
        return dict(_load())


def set_many(updates: dict):
    """Update multiple settings at once and persist. Thread-safe."""
    with _lock:
        store = _load()
        store.update(updates)
        _save()


def reset():
    """Reset all settings to defaults and persist. Thread-safe."""
    global _cache
    with _lock:
        _cache = dict(_DEFAULTS)
        _save()


def reload():
    """Force reload from disk (useful after external edits). Thread-safe."""
    global _cache
    with _lock:
        _cache = None
        _load()
