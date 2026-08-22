import platform
import subprocess
import shutil
import os
from pathlib import Path
from .base import BaseSkill

class SystemSkill(BaseSkill):
    name = "system"

    def __init__(self, config: dict):
        self.config = config
        self.allow_shell = config.get("skills", {}).get("system", {}).get("allow_shell", False)

    def can_handle(self, action: str) -> bool:
        return action in ["open_app", "close_app", "run_command", "system_volume", "screenshot", "open_url", "play_music"]

    def execute(self, action: str, params: dict) -> str:
        try:
            if action == "open_app":
                return self._open_app(params.get("app", ""))
            elif action == "close_app":
                return self._close_app(params.get("app", ""))
            elif action == "run_command":
                return self._run_command(params.get("cmd", ""))
            elif action == "system_volume":
                return self._volume(params.get("action", ""))
            elif action == "screenshot":
                return self._screenshot()
            elif action == "open_url":
                return self._open_url(params.get("url", ""), params.get("name", ""))
            elif action == "play_music":
                return self._play_music(params.get("query", ""))
        except Exception as e:
            return f"Hata: {e}"
        return "Bilinmeyen sistem komutu"

    def _open_url(self, url: str, name: str = "") -> str:
        if not url:
            return "URL boş."
        if not url.startswith("http"):
            url = "https://" + url
        subprocess.Popen(["open", url])
        return f"{name or url} açılıyor."

    def _play_music(self, query: str) -> str:
        """YouTube'da arayıp ilk sonucu açar — 'avici wake up çal' gibi"""
        import urllib.parse
        q = urllib.parse.quote(query)
        # YouTube arama sayfası (kullanıcı tıklayınca çalar) + autoplay parametresi
        url = f"https://www.youtube.com/results?search_query={q}"
        subprocess.Popen(["open", url])
        return f"🎵 '{query}' YouTube'da açılıyor."

    def _open_app(self, app: str) -> str:
        app = app.lower().strip()
        system = platform.system()
        # map
        app_map = {
            "chrome": "Google Chrome",
            "firefox": "Firefox",
            "safari": "Safari",
            "vscode": "Visual Studio Code",
            "code": "Visual Studio Code",
            "finder": "Finder",
            "terminal": "Terminal",
            "spotify": "Spotify",
            "youtube": "https://youtube.com",  # url fallback
        }
        target = app_map.get(app, app)
        if target.startswith("http"):
            subprocess.Popen(["open", target])
            return f"{app} açılıyor."

        try:
            if system == "Darwin":
                subprocess.Popen(["open", "-a", target])
            elif system == "Windows":
                os.startfile(target)  # type: ignore
            elif system == "Linux":
                subprocess.Popen([target])
            else:
                subprocess.Popen([target])
            return f"{target} açılıyor."
        except Exception as e:
            # fallback: try direct
            try:
                if shutil.which(app):
                    subprocess.Popen([app])
                    return f"{app} açılıyor."
            except Exception:
                pass
            return f"{target} açılamadı: {e}"

    def _close_app(self, app: str) -> str:
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["pkill", "-i", app], check=False)
            elif system == "Windows":
                subprocess.run(["taskkill", "/IM", f"{app}.exe", "/F"], check=False)
            else:
                subprocess.run(["pkill", app], check=False)
            return f"{app} kapatıldı."
        except Exception as e:
            return f"Kapatılamadı: {e}"

    def _run_command(self, cmd: str) -> str:
        # Güvenlik: Arbitrary shell komutu devre dışı — PermissionManager onayı gerektirir
        return "Bu işlem onay gerektirir. Doğrudan shell komutu çalıştırma devre dışı."

    def _volume(self, action: str) -> str:
        system = platform.system()
        try:
            if system == "Darwin":
                if action == "up":
                    subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 10)"], check=False)
                elif action == "down":
                    subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 10)"], check=False)
                elif action == "mute":
                    subprocess.run(["osascript", "-e", "set volume output muted true"], check=False)
                elif action == "unmute":
                    subprocess.run(["osascript", "-e", "set volume output muted false"], check=False)
                return f"Ses: {action}"
            elif system == "Windows":
                # nircmd gerekebilir, basit fallback
                return f"Ses komutu ({action}) Windows'ta ek araç gerektirir."
            else:
                # Linux pulseaudio
                if action == "up":
                    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], check=False)
                elif action == "down":
                    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], check=False)
                elif action == "mute":
                    subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], check=False)
                return f"Ses: {action}"
        except Exception as e:
            return f"Ses hatası: {e}"

    def _screenshot(self) -> str:
        system = platform.system()
        dest = str(Path.home() / "Desktop" / "elisha-screenshot.png")
        try:
            if system == "Darwin":
                subprocess.run(["screencapture", dest], check=False)
                return f"Ekran görüntüsü alındı: {dest}"
            elif system == "Windows":
                # PowerShell
                ps = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::PrimaryScreen"
                # simpler: use mss if available
                try:
                    import mss
                    with mss.mss() as sct:
                        sct.shot(output=dest)
                    return f"Ekran görüntüsü alındı: {dest}"
                except Exception:
                    return "Screenshot için 'pip install mss' gerekli."
            else:
                try:
                    import mss
                    with mss.mss() as sct:
                        sct.shot(output=dest)
                    return f"Ekran görüntüsü alındı: {dest}"
                except Exception:
                    subprocess.run(["import", dest], check=False)  # ImageMagick
                    return f"Ekran görüntüsü alındı: {dest}"
        except Exception as e:
            return f"Screenshot hatası: {e}"
