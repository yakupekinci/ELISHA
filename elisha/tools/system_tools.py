import datetime
import platform
import subprocess
import shutil
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


class GetTimeTool(Tool):
    name = "get_time"
    description = ("Sistemden geçerli saati öğrenmek için kullanılır. Kullanıcı saat kaç diye sorduğunda "
                   "veya saati bilmen gereken her durumda kullan. Parametre gerekmez.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        now = datetime.datetime.now()
        return ToolResult(True, self.name,
                          message=f"Şu an saat {now.strftime('%H:%M')}.",
                          data={"time": now.strftime("%H:%M"), "datetime": now.isoformat()})


class GetDateTool(Tool):
    name = "get_date"
    description = ("Sistemden bugünün tarihini ve gününü öğrenmek için kullanılır. "
                   "Kullanıcı tarih/gün sorduğunda kullan. Parametre gerekmez.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.SAFE

    GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    AYLAR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        now = datetime.datetime.now()
        tr = f"{now.day} {self.AYLAR[now.month]} {now.year}, {self.GUNLER[now.weekday()]}"
        return ToolResult(True, self.name,
                          message=f"Bugün {tr}.",
                          data={"date": now.strftime("%Y-%m-%d"), "turkce": tr})


class GetSystemInfoTool(Tool):
    name = "get_system_info"
    description = ("İşletim sistemi, makine mimarisi ve Python sürümü gibi temel sistem bilgilerini verir. "
                   "Kullanıcı sistem/about bilgisi istediğinde kullan.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        info = {
            "os": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "hostname": platform.node(),
        }
        return ToolResult(True, self.name,
                          message=f"Sistem: {info['os']} ({info['machine']}), Python {info['python']}.",
                          data=info)


class SetVolumeTool(Tool):
    name = "set_volume"
    description = ("Sistem ses seviyesini değiştirmek için kullanılır. action parametresi şunlardan biri: "
                   "'up' (yükselt), 'down' (kıs), 'mute' (sessize al), 'unmute' (sesi geri aç). "
                   "Kullanıcı sesi aç/kıs/sessize al derse kullan.")
    parameters = {
        "type": "object",
        "properties": {"action": {"type": "string",
                                  "enum": ["up", "down", "mute", "unmute"],
                                  "description": "Ses işlemi"}},
        "required": ["action"],
    }
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        action = args.get("action", "")
        system = platform.system()
        try:
            if system == "Darwin":
                scripts = {
                    "up": "set volume output volume (output volume of (get volume settings) + 10)",
                    "down": "set volume output volume (output volume of (get volume settings) - 10)",
                    "mute": "set volume output muted true",
                    "unmute": "set volume output muted false",
                }
                if action not in scripts:
                    return ToolResult(False, self.name, error=f"Geçersiz action: {action}")
                _run(["osascript", "-e", scripts[action]])
                labels = {"up": "Sesi yükselttim.", "down": "Sesi kıstım.",
                          "mute": "Sessize aldım.", "unmute": "Sesi açtım."}
                return ToolResult(True, self.name, message=labels[action], data={"action": action})
            if system == "Windows":
                return ToolResult(False, self.name, error="Windows ses kontrolü ek araç gerektirir.")
            pactl_map = {
                "up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
                "down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
                "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
                "unmute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
            }
            _run(pactl_map[action])
            return ToolResult(True, self.name, message=f"Ses: {action}", data={"action": action})
        except Exception as e:
            return ToolResult(False, self.name, error=str(e))


class OpenApplicationTool(Tool):
    name = "open_application"
    description = ("macOS üzerinde kurulu bir uygulamayı açmak için kullanılır. Kullanıcı açıkça bir uygulama "
                   "açmasını istediğinde kullan (örn. 'Chrome'u aç'). app parametresine uygulama adını yaz: "
                   "chrome, safari, firefox, vscode, finder, terminal, spotify, notes, calculator vb. "
                   "Web sitesi açmak için bunu DEĞİL open_url aracını kullan.")
    parameters = {
        "type": "object",
        "properties": {"app": {"type": "string", "description": "Uygulama adı, örn. chrome"}},
        "required": ["app"],
    }
    risk_level = RiskLevel.LOW

    APP_MAP = {
        "chrome": "Google Chrome",
        "firefox": "Firefox",
        "safari": "Safari",
        "vscode": "Visual Studio Code",
        "code": "Visual Studio Code",
        "finder": "Finder",
        "terminal": "Terminal",
        "spotify": "Spotify",
        "notes": "Notes",
        "calculator": "Calculator",
        "mail": "Mail",
        "messages": "Messages",
    }

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        app = str(args.get("app", "")).lower().strip()
        if not app:
            return ToolResult(False, self.name, error="Uygulama adı boş.")
        target = self.APP_MAP.get(app, app)
        system = platform.system()
        try:
            if target.startswith("http"):
                subprocess.Popen(["open", target])
                return ToolResult(True, self.name, message=f"{app} açılıyor.", data={"app": app})
            if system == "Darwin":
                subprocess.Popen(["open", "-a", target])
            elif system == "Windows":
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                subprocess.Popen([target])
            return ToolResult(True, self.name, message=f"{target} açılıyor.", data={"app": target})
        except Exception as e:
            try:
                if shutil.which(app):
                    subprocess.Popen([app])
                    return ToolResult(True, self.name, message=f"{app} açılıyor.", data={"app": app})
            except Exception:
                pass
            return ToolResult(False, self.name, error=f"{target} açılamadı: {e}")


class CloseApplicationTool(Tool):
    name = "close_application"
    description = ("Çalışan bir uygulamayı kapatmak için kullanılır. Kullanıcı açıkça bir uygulamayı kapatmayı "
                   "istediğinde kullan. app parametresine uygulama adını yaz, örn. chrome.")
    parameters = {
        "type": "object",
        "properties": {"app": {"type": "string", "description": "Kapatılacak uygulama adı"}},
        "required": ["app"],
    }
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        app = str(args.get("app", "")).strip()
        if not app:
            return ToolResult(False, self.name, error="Uygulama adı boş.")
        system = platform.system()
        try:
            if system == "Darwin":
                _run(["pkill", "-i", app])
            elif system == "Windows":
                _run(["taskkill", "/IM", f"{app}.exe", "/F"])
            else:
                _run(["pkill", app])
            return ToolResult(True, self.name, message=f"{app} kapatıldı.", data={"app": app})
        except Exception as e:
            return ToolResult(False, self.name, error=f"Kapatılamadı: {e}")


class TakeScreenshotTool(Tool):
    name = "take_screenshot"
    description = ("Ekran görüntüsü alır ve masaüstüne kaydeder. Kullanıcı ekran görüntüsü/screenshot isterse "
                   "kullan. Görüntüyü analiz edemezsin, sadece kaydedersin.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        system = platform.system()
        dest = str(Path.home() / "Desktop" / "elisha-screenshot.png")
        try:
            if system == "Darwin":
                _run(["screencapture", dest])
                return ToolResult(True, self.name,
                                  message=f"Ekran görüntüsü alındı: {dest}", data={"path": dest})
            try:
                import mss
                with mss.mss() as sct:
                    sct.shot(output=dest)
                return ToolResult(True, self.name,
                                  message=f"Ekran görüntüsü alındı: {dest}", data={"path": dest})
            except Exception:
                if system == "Windows":
                    return ToolResult(False, self.name, error="Screenshot için 'pip install mss' gerekli.")
                _run(["import", dest])
                return ToolResult(True, self.name,
                                  message=f"Ekran görüntüsü alındı: {dest}", data={"path": dest})
        except Exception as e:
            return ToolResult(False, self.name, error=f"Screenshot hatası: {e}")


class PlayMusicTool(Tool):
    name = "play_music"
    description = ("Müzik/şarkı çalmak için kullanılır. YouTube'da arama yapıp ilk videoyu "
                   "otomatik oynatır. Kullanıcı şarkı/müzik/çal derse kullan. "
                   "query'e sanatçı + şarkı adını yaz, örn. 'Tarkan Şımarık' veya 'edm mix 2024'.")
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Şarkı adı veya sanatçı, örn. 'Tarkan Şımarık'"}},
        "required": ["query"],
    }
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(False, self.name, error="Şarkı adı boş.")
        try:
            # Önce YouTube'da ilk video ID'sini bul
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            import urllib.request as _req
            headers = {"User-Agent": "Mozilla/5.0"}
            req = _req.Request(search_url, headers=headers)
            html = _req.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore")
            # video ID'yi çek
            import re as _re
            m = _re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
            if m:
                vid = m.group(1)
                play_url = f"https://www.youtube.com/watch?v={vid}&autoplay=1"
            else:
                play_url = search_url
            subprocess.Popen(["open", play_url])
            return ToolResult(True, self.name,
                              message=f"'{query}' çalıyor 🎵", data={"query": query, "url": play_url})
        except Exception as e:
            # Fallback: arama sayfası aç
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            subprocess.Popen(["open", url])
            return ToolResult(True, self.name,
                              message=f"'{query}' YouTube'da aranıyor.", data={"query": query})


class OpenUrlTool(Tool):
    name = "open_url"
    description = ("Bir web sitesini veya URL'yi varsayılan tarayıcıda açmak için kullanılır. "
                   "Kullanıcı bir site isterse kullan, örn. url='youtube.com', name='YouTube'. "
                   "Uygulama açmak için open_application kullan.")
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Açılacak adres, örn. youtube.com"},
            "name": {"type": "string", "description": "Sitenin görünen adı, örn. YouTube"},
        },
        "required": ["url"],
    }
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        url = str(args.get("url", "")).strip()
        name = str(args.get("name", "") or "").strip()
        if not url:
            return ToolResult(False, self.name, error="URL boş.")
        if not url.startswith("http"):
            url = "https://" + url
        try:
            subprocess.Popen(["open", url])
            return ToolResult(True, self.name,
                              message=f"{name or url} açılıyor.", data={"url": url})
        except Exception as e:
            return ToolResult(False, self.name, error=str(e))
