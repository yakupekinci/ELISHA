"""Görü aracı — ekran görüntüsünü ücretsiz vision modelleriyle analiz eder.
Desen: FatihMakes/Mark-XXXIX-OR or_client.py vision havuzundan uyarlanmıştır."""
import base64
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


class AnalyzeScreenTool(Tool):
    name = "analyze_screen"
    description = (
        "Kullanıcının ekranına BAKAR ve görüp analiz eder. 'Ekranda ne var', "
        "'ekranıma bak', 'bu hata nedir', 'şu an ne yapıyorum' gibi görme gerektiren "
        "isteklerde kullan. Opsiyonel 'prompt' ile neye bakılacağını belirt "
        "(örn: 'ekrandaki hata mesajını oku'). Ekran görüntüsü ücretsiz vision "
        "modeliyle analiz edilir; sonuç doğal Türkçe döner.")
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Ekranda neye bakılacağı / ne sorulacağı (opsiyonel)"
            }
        },
        "required": []
    }
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        question = str((args or {}).get("prompt") or
                       "Bu ekranda ne var? Kullanıcının ne yaptığını kısaca açıkla.").strip()

        shot = Path("/tmp/elisha_vision.png")
        try:
            if platform.system() == "Darwin":
                subprocess.run(["screencapture", "-x", "-t", "png", str(shot)],
                               capture_output=True, timeout=12, check=False)
            else:
                import mss
                with mss.mss() as sct:
                    sct.shot(output=str(shot))
        except Exception as e:
            return ToolResult(False, self.name, error=f"Ekran görüntüsü alınamadı: {e}")

        if not shot.exists() or shot.stat().st_size < 2000:
            return ToolResult(False, self.name, error=(
                "Ekran görüntüsü boş geldi — macOS Ekran Kaydı izni gerekebilir "
                "(Sistem Ayarları → Gizlilik → Ekran Kaydı → Python)."))

        # Siyah/boş görüntü tespiti (izin yoksa macOS sessizce siyah çeker)
        try:
            from .system_tools import TakeScreenshotTool
            perm_err = TakeScreenshotTool._screen_recording_missing(str(shot))
            if perm_err:
                return ToolResult(False, self.name, error=perm_err)
        except Exception:
            pass

        try:
            img_b64 = base64.b64encode(shot.read_bytes()).decode()
        except Exception as e:
            return ToolResult(False, self.name, error=f"Görüntü okunamadı: {e}")

        try:
            from ..llm.providers import OpenRouterProvider
            op = OpenRouterProvider(self.config)
            answer = op.vision(question, img_b64, mime="image/png")
        except Exception as e:
            return ToolResult(False, self.name, error=f"Görü analizi başarısız: {e}")

        return ToolResult(True, self.name,
                          message=answer[:900],
                          data={"prompt": question[:120]})
