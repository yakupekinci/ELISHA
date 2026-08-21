import os
import yaml
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

def load_config(path=None) -> dict:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    # allow local override
    local_path = cfg_path.parent / "config.local.yaml"
    if local_path.exists():
        cfg_path = local_path
    if not cfg_path.exists():
        return {}
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data

def get(cfg: dict, dotted: str, default=None):
    cur = cfg
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur
