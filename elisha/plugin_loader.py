"""ELİŞA Eklenti Sistemi — drop-in araç desteği.
Desen: FatihMakes/Mark-LI core/plugin_loader.py'den ELISHA Tool mimarisine uyarlandı.

Kullanım: plugins/ klasörüne bir .py dosyası bırak (_ ile başlamayan), içinde:

    PLUGIN = {
        "name": "benim_araç",              # benzersiz snake_case
        "description": "Ne zaman kullanılacağı (LLM bunu okur)",
        "parameters": {"type": "object", "properties": {...}, "required": []},
        "risk": "LOW",                     # opsiyonel: SAFE/LOW/MEDIUM/HIGH
    }

    def run(parameters: dict) -> str:
        return "Kullanıcıya söylenecek doğal cevap"

Restart'ta otomatik keşfedilir. Kırık plugin ASLA uygulamayı düşürmez;
çekirdek araçla isim çakışması reddedilir.
"""
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .tools.base import Tool, ToolResult, RiskLevel

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_DEFAULT_PARAMS = {"type": "object", "properties": {}, "required": []}
_RISK_MAP = {"SAFE": RiskLevel.SAFE, "LOW": RiskLevel.LOW,
             "MEDIUM": RiskLevel.MEDIUM, "HIGH": RiskLevel.HIGH,
             "CRITICAL": RiskLevel.CRITICAL}


@dataclass
class PluginRecord:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: dict(_DEFAULT_PARAMS))
    run: Optional[Callable] = None
    file: str = ""
    risk: RiskLevel = RiskLevel.LOW
    valid: bool = False
    error: str = ""


def _validate(module, filename: str) -> PluginRecord:
    """PluginRecord döner; sorun varsa valid=False + error. Asla raise etmez."""
    stem = Path(filename).stem
    meta = getattr(module, "PLUGIN", None)
    if not isinstance(meta, dict):
        return PluginRecord(name=stem, file=filename,
                            error="PLUGIN dict sabiti eksik.")
    name = meta.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return PluginRecord(name=str(name or stem), file=filename,
                            error="PLUGIN['name'] geçersiz (harf/_ ile başlamalı).")
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return PluginRecord(name=name, file=filename,
                            error="PLUGIN['description'] boş.")
    params = meta.get("parameters") or dict(_DEFAULT_PARAMS)
    if not isinstance(params, dict):
        return PluginRecord(name=name, file=filename,
                            error="PLUGIN['parameters'] dict olmalı.")
    params = dict(params)
    params["type"] = str(params.get("type", "object")).lower()  # OBJECT→object normalize
    params.setdefault("properties", {})
    params.setdefault("required", [])
    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        return PluginRecord(name=name, file=filename,
                            error="run(parameters) fonksiyonu eksik.")
    risk = _RISK_MAP.get(str(meta.get("risk", "LOW")).upper(), RiskLevel.LOW)
    return PluginRecord(name=name, description=desc.strip(), parameters=params,
                        run=run_fn, file=filename, risk=risk, valid=True)


def discover_plugins(plugins_dir: Path, core_tool_names: set,
                     logger: Callable[[str], None] = print) -> Dict[str, PluginRecord]:
    """plugins/*.py tarar (alt çizgiyle başlayanlar atlanır).
    Import/validasyon hataları ve isim çakışmaları loglanıp atlanır — asla raise etmez."""
    plugins_dir.mkdir(parents=True, exist_ok=True)
    valid: Dict[str, PluginRecord] = {}
    for path in sorted(plugins_dir.glob("*.py"), key=lambda p: p.name):
        if path.name.startswith("_"):
            continue
        mod_name = f"elisha_plugins.{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                raise ImportError("import spec kurulamadı")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(mod_name, None)
                raise
            rec = _validate(module, path.name)
            if rec.valid and rec.name in core_tool_names:
                rec = PluginRecord(name=rec.name, file=path.name,
                                   error=f"'{rec.name}' çekirdek aracıyla çakışıyor — reddedildi.")
            elif rec.valid and rec.name in valid:
                rec = PluginRecord(name=rec.name, file=path.name,
                                   error=f"'{rec.name}' zaten '{valid[rec.name].file}' tarafından kullanılıyor.")
            if rec.valid:
                valid[rec.name] = rec
                logger(f"🧩 Plugin yüklendi: {rec.name} ({path.name})")
            else:
                logger(f"⚠️ Plugin reddedildi: {path.name} — {rec.error}")
        except Exception as e:
            logger(f"⚠️ Plugin kırık: {path.name} — {e}")
    return valid


def make_plugin_tool(rec: PluginRecord, config: dict) -> Tool:
    """PluginRecord → ELISHA Tool adaptörü."""

    class PluginTool(Tool):
        _rec = rec

        def __init__(self, cfg):
            super().__init__(cfg)
            self.name = rec.name
            self.description = rec.description
            self.parameters = rec.parameters
            self.risk_level = rec.risk

        def execute(self, args: Dict[str, Any]) -> ToolResult:
            try:
                out = self._rec.run(dict(args or {}))
                text = str(out if out is not None else "Tamam.").strip()
                return ToolResult(True, self.name, message=text[:900])
            except Exception as e:
                return ToolResult(False, self.name,
                                  error=f"'{self._rec.name}' eklentisi hata verdi: {e}")

    return PluginTool(config)
