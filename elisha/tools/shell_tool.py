"""AŞAMA 6 — Shell komut aracı (VARSAYILAN KAPALI).

config.yaml'da:
  tools:
    run_shell:
      enabled: true          # yoksa/kapalıysa araç hiç kayıtlı olmaz
      allowlist:             # izin verilen komut önekleri (regex değil, kelime listesi)
        - ls
        - df
        - uptime
      timeout: 10            # saniye

Risk seviyesi CRITICAL -> PermissionManager her seferinde onay ister.
"""
import shlex
import subprocess
from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


class RunShellTool(Tool):
    name = "run_shell"
    description = (
        "Kullanıcı adına güvenli bir terminal komutu çalıştırır. SADECE allowlist'teki "
        "komutlara izin var. Dosya listeleme, disk durumu gibi sistem sorguları için kullan. "
        "command parametresi zorunlu."
    )
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Çalıştırılacak komut"}},
        "required": ["command"],
    }
    risk_level = RiskLevel.CRITICAL

    def __init__(self, config: Dict[str, Any] = None):
        cfg = ((config or {}).get("tools", {}) or {}).get("run_shell", {}) or {}
        self._allow = [str(a).lower() for a in cfg.get(
            "allowlist", ["ls", "df", "uptime", "whoami", "date", "pwd"])]
        self._timeout = int(cfg.get("timeout", 10))

    def confirm_message(self, args: Dict[str, Any]) -> str:
        return f"Şu terminal komutu çalıştırılsın mı? → {args.get('command', '?')}"

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        cmd = str(args.get("command", "")).strip()
        if not cmd:
            return ToolResult(False, self.name, error="Komut boş.")
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return ToolResult(False, self.name, error="Komut ayrıştırılamadı.")
        if not parts or parts[0].lower() not in self._allow:
            allowed = ", ".join(self._allow)
            return ToolResult(False, self.name,
                              error=f"'{parts[0] if parts else cmd}' izinli değil. İzinli: {allowed}")
        try:
            out = subprocess.run(parts, capture_output=True, text=True,
                                 timeout=self._timeout)
            text = (out.stdout or "").strip() or (out.stderr or "").strip()
            if len(text) > 1500:
                text = text[:1500] + "... (kısaltıldı)"
            ok = out.returncode == 0
            return ToolResult(ok, self.name,
                              message=text or "(çıktı yok)",
                              error=None if ok else f"exit={out.returncode}")
        except subprocess.TimeoutExpired:
            return ToolResult(False, self.name, error=f"{self._timeout}s içinde bitmedi.")
        except Exception as e:
            return ToolResult(False, self.name, error=f"Komut hatası: {e}")
