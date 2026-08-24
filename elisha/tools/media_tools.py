"""Sistem kontrol araçları: medya, ses, batarya, uygulama yönetimi."""
import re
import subprocess
from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


def _osa(script: str, timeout: int = 8) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "osascript hatası").strip()[:120])
    return (r.stdout or "").strip()


class MediaControlTool(Tool):
    name = "media_control"
    description = (
        "Müzik çaları kontrol eder: çal/duraklat/sonraki/önceki. 'Müziği durdur', "
        "'sıradaki şarkı', 'Spotify'da şarkı aç' gibi isteklerde kullanılır. "
        "player: spotify | music | auto (varsayılan auto).")
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "description": "toggle | play | pause | next | previous"},
            "player": {"type": "string",
                       "description": "spotify | music | auto (varsayılan auto)"}},
        "required": ["action"],
    }
    risk_level = RiskLevel.LOW
    _CMDS = {
        "toggle": {"spotify": "playpause", "music": "playpause"},
        "play":   {"spotify": "play",      "music": "play"},
        "pause":  {"spotify": "pause",     "music": "pause"},
        "next":   {"spotify": "next track","music": "next track"},
        "previous":{"spotify":"previous track","music": "previous track"},
    }

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        action = str((args or {}).get("action", "toggle")).lower()
        player = str((args or {}).get("player", "auto")).lower()
        if action not in self._CMDS:
            return ToolResult(False, self.name,
                              error=f"Bilinmeyen eylem: {action} (toggle/play/pause/next/previous)")
        targets = ("spotify", "music") if player == "auto" else (player,)
        last_err = ""
        for app in targets:
            try:
                running = _osa(f'application "{app.title()}" is running').lower() == "true"
                if player == "auto" and not running:
                    continue
                _osa(f'tell application "{app.title()}" to {self._CMDS[action][app]}')
                tr = {"toggle": "çal/duraklat", "play": "çalıyor", "pause": "duraklatıldı",
                      "next": "sıradaki şarkı", "previous": "önceki şarkı"}[action]
                # Şarkı adını da ver
                try:
                    track = _osa(f'tell application "{app.title()}" to name of current track')
                    artist = _osa(f'tell application "{app.title()}" to artist of current track')
                    return ToolResult(True, self.name,
                                      message=f"🎵 {tr}: {artist} — {track}",
                                      data={"app": app})
                except Exception:
                    return ToolResult(True, self.name,
                                      message=f"🎵 {tr} ({app.title()})", data={"app": app})
            except Exception as e:
                last_err = str(e)
        return ToolResult(False, self.name,
                          error=f"Müzik çalı bulunamadı (Spotify/Music açık mı?). {last_err}")


class AppManagerTool(Tool):
    name = "app_manager"
    description = (
        "Uygulama açar, kapatır veya açık uygulamaları listeler. 'Safari'yi aç', "
        "'Chrome'u kapat', 'hangi uygulamalar açık' gibi isteklerde kullanılır. "
        "action: open | quit | list")
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "open | quit | list"},
            "name": {"type": "string",
                     "description": "Uygulama adı (open/quit için), örn: Safari"}},
        "required": ["action"],
    }
    risk_level = RiskLevel.MEDIUM  # quit veri kaybettirebilir

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        a = args or {}
        action = str(a.get("action", "")).lower()
        name = str(a.get("name", "")).strip()
        try:
            if action == "list":
                out = _osa(
                    'tell application "System Events" to '
                    'get name of every process whose background only is false', 10)
                apps = [x.strip() for x in out.split(",") if x.strip()]
                apps = [x for x in apps if x != "Python"]
                return ToolResult(True, self.name,
                                  message="Açık uygulamalar: " + ", ".join(apps[:12]),
                                  data={"apps": apps})
            if not name:
                return ToolResult(False, self.name, error=f"'{action}' için uygulama adı gerekli.")
            if action == "open":
                subprocess.Popen(["open", "-a", name])
                return ToolResult(True, self.name, message=f"{name} açıldı.")
            if action == "quit":
                _osa(f'tell application "{name}" to quit', 10)
                return ToolResult(True, self.name, message=f"{name} kapatıldı.")
            return ToolResult(False, self.name, error=f"Bilinmeyen eylem: {action}")
        except Exception as e:
            return ToolResult(False, self.name, error=f"Uygulama işlemi başarısız ({name}): {e}")
