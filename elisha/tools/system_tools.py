import datetime
import platform
import subprocess
import shutil
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

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
        # SELF-KORUMA: ELİŞA'yı ve macOS çekirdek süreçlerini kapatamayız.
        _PROTECTED = (
            "python", "elisha", "menubar", "wake_daemon", "desktop_app",
            "server", "loginwindow", "windowserver", "kernel", "launchd",
            "dock", "systemuiserver", "coreaudiod",
        )
        low = app.lower()
        for p in _PROTECTED:
            if p in low or low in p and len(low) > 2:
                return ToolResult(False, self.name,
                                  error=(f"'{app}' kapatılamaz — bu süreç ELİŞA'nın veya "
                                         f"macOS'un çalışması için gerekli."))
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
                # Ekran Kaydı izni yoksa macOS sessizce BOŞ/siyah görüntü üretir.
                # Görüntüyü kontrol edip kullanıcıya net yönlendirme ver.
                perm_err = self._screen_recording_missing(dest)
                if perm_err:
                    return ToolResult(False, self.name, error=perm_err)
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

    @staticmethod
    def _screen_recording_missing(path: str) -> Optional[str]:
        """Best-effort izin tespiti: dosya yoksa/boşsa veya piksel varyansı
        neredeyse sıfırsa (düz renk) → Screen Recording izni verilmemiş.
        PIL yoksa kontrol atlanır (yanlış pozitif üretmemek için)."""
        try:
            from PIL import Image  # type: ignore
            import numpy as _np
            p = Path(path)
            if not p.exists() or p.stat().st_size < 1024:
                return ("Ekran görüntüsü boş geldi. Sistem Ayarları → Gizlilik ve Güvenlik "
                        "→ Ekran Kaydı'ndan terminal/uygulamaya izin ver.")
            img = Image.open(p).convert("L")
            small = img.resize((min(img.width, 256), min(img.height, 256)))
            std = float(_np.asarray(small).std())
            if std < 2.5:
                return ("Görüntü tamamen boş — muhtemelen Ekran Kaydı izni eksik. "
                        "Sistem Ayarları → Gizlilik ve Güvenlik → Ekran Kaydı'ndan "
                        "izin verdikten sonra tekrar dene.")
        except ImportError:
            pass
        except Exception:
            pass
        return None


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


class GetLocationTool(Tool):
    name = "get_location"
    description = ("Kullanıcının bulunduğu konumu öğrenmek için kullanılır. IP tabanlı konum algılama yapar. "
                   "Kullanıcı 'neredeyim', 'konumum ne', 'hangi şehirdeyim' gibi sorduğunda kullan. "
                   "Parametre gerekmez. Şehir, ülke, koordinat ve zaman dilimi döndürür.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """IP tabanlı konum — HTTPS üzerinden (şifresiz HTTP kullanılmaz).
        Sıra: ipapi.co → ipwho.is → macOS CoreLocation."""
        import urllib.request
        import json as _json

        def _fetch_json(url: str, timeout: float = 5):
            req = urllib.request.Request(url, headers={"User-Agent": "ELISHA/4.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _json.loads(resp.read().decode())

        # 1) ipapi.co — HTTPS ücretsiz katman (~1000 istek/gün, anahtar opsiyonel)
        try:
            data = _fetch_json("https://ipapi.co/json/")
            if data.get("error"):
                raise RuntimeError(data.get("reason", "ipapi hata"))
            city = data.get("city", "Bilinmeyen")
            region = data.get("region", "")
            country = data.get("country_name", "")
            lat = data.get("latitude", 0)
            lon = data.get("longitude", 0)
            tz = data.get("timezone", "")
            ip = data.get("ip", "")
            location_str = f"{city}, {region}, {country}" if region else f"{city}, {country}"
            return ToolResult(True, self.name,
                              message=f"Konumun: {location_str} (koordinat: {lat}, {lon})",
                              data={"city": city, "region": region, "country": country,
                                    "lat": lat, "lon": lon, "timezone": tz,
                                    "ip": ip, "location": location_str, "source": "ipapi.co"})
        except Exception:
            pass
        # 2) ipwho.is — HTTPS, anahtarsız yedek
        try:
            data = _fetch_json("https://ipwho.is/")
            if not data.get("success", True):
                raise RuntimeError(str(data.get("message", "")))
            city = data.get("city") or "Bilinmeyen"
            region = data.get("region") or ""
            country = data.get("country") or ""
            lat = data.get("latitude", 0)
            lon = data.get("longitude", 0)
            tz = (data.get("timezone") or {}).get("id", "")
            ip = (data.get("connection") or {}).get("ip", "")
            location_str = f"{city}, {region}, {country}" if region else f"{city}, {country}"
            return ToolResult(True, self.name,
                              message=f"Konumun: {location_str} (koordinat: {lat}, {lon})",
                              data={"city": city, "region": region, "country": country,
                                    "lat": lat, "lon": lon, "timezone": tz,
                                    "ip": ip, "location": location_str, "source": "ipwho.is"})
        except Exception:
            pass
        # 3) macOS CoreLocation — son çare (izin gerektirir, GPS varsa en kesin)
        try:
            result = subprocess.run(
                ["swift", "-e", """
import CoreLocation
import Foundation
let mgr = CLLocationManager()
mgr.requestWhenInUseAuthorization()
let loc = mgr.location
if let l = loc {
    print("\\(l.coordinate.latitude),\\(l.coordinate.longitude)")
} else {
    print("UNAVAILABLE")
}
"""],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() and result.stdout.strip() != "UNAVAILABLE":
                parts = result.stdout.strip().split(",")
                lat, lon = float(parts[0]), float(parts[1])
                return ToolResult(True, self.name,
                                  message=f"GPS konumun: {lat}, {lon}",
                                  data={"lat": lat, "lon": lon, "source": "corelocation"})
        except Exception:
            pass
        return ToolResult(False, self.name,
                          error="Konum alınamadı — internet bağlantını kontrol et "
                                "(konum servisleri yanıt vermedi).")


def _osascript(script: str, timeout=15) -> subprocess.CompletedProcess:
    return _run(["osascript", "-e", script], timeout=timeout)


def _friendly_apple_err(stderr: str) -> str:
    """AppleScript hatalarını Türkçe ve eyleme dönük mesaja çevir."""
    s = stderr or ""
    if "timed out" in s or "TimeoutExpired" in s:
        return ("Uygulama erişim onayı bekliyor. Ekrandaki izin penceresini onayla "
                "(veya Sistem Ayarları → Gizlilik ve Güvenlik → Otomasyon'dan izin ver).")
    if "-1743" in s:
        return ("macOS bu uygulamaya erişim iznini engelledi. "
                "Sistem Ayarları → Gizlilik ve Güvenlik → Otomasyon'dan izin ver.")
    if "-1712" in s or "zaman aşımı" in s.lower():
        return ("Uygulama yanıt vermiyor. Ekrandaki izin penceresini onayla ve tekrar dene.")
    if "not signed in" in s.lower() or "iCloud" in s:
        return "Bu uygulama iCloud hesabı gerektiriyor; giriş yapılmamış görünüyor."
    return s.strip()[:150] or "Bilinmeyen uygulama hatası"


class SetReminderTool(Tool):
    name = "set_reminder"
    description = ("Apple Hatırlatıcılar'a (Reminders) hatırlatma ekler. Kullanıcı 'bana X'i hatırlat', "
                   "'yarın saat 5'te X hatırlatıcısı kur' derse kullan. Parametreler: title (zorunlu), "
                   "due (opsiyonel, örn 'yarın 17:00' veya '5 dakika sonra' — doğal dil serbest).")
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Hatırlatmanın konusu"},
            "due": {"type": "string", "description": "Ne zaman (boşsa tarihsiz listeye eklenir)"},
        },
        "required": ["title"],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        title = str(args.get("title", "")).strip()
        due = str(args.get("due", "") or "").strip()
        if not title:
            return ToolResult(False, self.name, error="Başlık gerekli")
        # LLM'e relative time'ı mutlak tarihe çevirtmek yerine basit ayrıştırma
        import re, datetime as _dt
        due_date = None
        now = _dt.datetime.now()
        d = due.lower()
        m = re.search(r'(\d{1,2})[:.](\d{2})', d)
        hour, minute = (int(m.group(1)), int(m.group(2))) if m else None
        day_delta = 0
        if "yarın" in d: day_delta = 1
        elif "haftaya" in d: day_delta = 7
        elif "bugün" in d: day_delta = 0
        if "dakika sonra" in d or "dk sonra" in d:
            m2 = re.search(r'(\d+)\s*(dakika|dk)', d)
            n = int(m2.group(1)) if m2 else 5
            due_date = now + _dt.timedelta(minutes=n)
        elif hour is not None:
            due_date = (now + _dt.timedelta(days=day_delta)).replace(
                hour=hour, minute=minute, second=0, microsecond=0)
            if due_date < now and day_delta == 0:
                due_date += _dt.timedelta(days=1)  # geçmiş saat → yarına al
        if due_date:
            iso = due_date.strftime("%Y-%m-%dT%H:%M:%S")
            safe_title = title.replace("\\", "'").replace('"', "'")
            script = (f'tell application "Reminders" to make new reminder with properties '
                      f'{{name:"{safe_title}", due date:date "{iso}"}}')
        else:
            safe_title = title.replace("\\", "'").replace('"', "'")
            script = f'tell application "Reminders" to make new reminder with properties {{name:"{safe_title}"}}'
        try:
            r = _osascript(script)
            if r.returncode != 0:
                return ToolResult(False, self.name, error=f"Hatırlatıcı eklenemedi: {_friendly_apple_err(r.stderr)}")
            when = due_date.strftime("%d.%m %H:%M") if due_date else "tarihsiz"
            return ToolResult(True, self.name,
                              message=f"'{title}' hatırlatıcısı kuruldu ({when}).",
                              data={"title": title, "when": when})
        except subprocess.TimeoutExpired:
            return ToolResult(False, self.name,
                              error=f"Hatırlatıcı eklenemedi: {_friendly_apple_err('timed out')}")
        except Exception as e:
            return ToolResult(False, self.name, error=_friendly_apple_err(str(e)))


class CreateNoteTool(Tool):
    name = "create_note"
    description = ("Apple Notlar'a (Notes) not oluşturur. Kullanıcı 'not al', 'şunu notlara ekle' derse kullan. "
                   "Parametreler: title (zorunlu), body (opsiyonel).")
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Not başlığı"},
            "body": {"type": "string", "description": "Not içeriği"},
        },
        "required": ["title"],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        title = str(args.get("title", "")).strip()[:200]
        body = str(args.get("body", "")).strip()[:2000]
        if not title:
            return ToolResult(False, self.name, error="Başlık gerekli")
        safe_title = title.replace('"', "'")
        safe_body = body.replace('"', "'")
        if body:
            script = (f'tell application "Notes" to make new note with properties '
                      f'{{name:"{safe_title}", body:"{safe_body}<br>"}}')
        else:
            script = f'tell application "Notes" to make new note with properties {{body:"{safe_title}<br>"}}'
        try:
            r = _osascript(script)
            if r.returncode != 0:
                return ToolResult(False, self.name, error=f"Not oluşturulamadı: {_friendly_apple_err(r.stderr)}")
            return ToolResult(True, self.name, message=f"Not oluşturuldu: {title}",
                              data={"title": title})
        except subprocess.TimeoutExpired:
            return ToolResult(False, self.name,
                              error=f"Not oluşturulamadı: {_friendly_apple_err('timed out')}")
        except Exception as e:
            return ToolResult(False, self.name, error=_friendly_apple_err(str(e)))


class BatteryTool(Tool):
    name = "get_battery"
    description = ("Mac'in pil durumu ve güç bağlantısını öğrenir. Kullanıcı 'pilim ne kadar', "
                   "'şarj durumum' derse veya pil bilgisi gerektiğinde kullan. Parametre gerekmez.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        r = _run(["pmset", "-g", "batt"], timeout=5)
        out = r.stdout.strip()
        # Örn: "Now drawing from 'AC Power' / -InternalBattery-0 (id=...)	92%; discharging; 4:20 remaining..."
        import re
        pct = re.search(r'(\d+)%', out)
        state = "şarjda" if "AC Power" in out else "pilde"
        remaining = ""
        m = re.search(r'(\d+:\d+)\s+remaining', out)
        if m:
            remaining = f", tahmini {m.group(1)} kaldı"
        if pct:
            msg = f"Pil %{pct.group(1)} ({state}{remaining})."
            return ToolResult(True, self.name, message=msg,
                              data={"percent": int(pct.group(1)), "state": state})
        return ToolResult(False, self.name, error="Pil bilgisi okunamadı")


class ScreenContextTool(Tool):
    name = "get_screen_context"
    description = ("Kullanıcının şu an hangi uygulamada olduğunu ve açık pencereleri öğrenir. "
                   "ELİŞA bağlam sorduğunda ('şu an ne yapıyorum', 'ekranda ne var') kullanılır. Parametre gerekmez.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            front = _osascript(
                'tell application "System Events" to get name of first process whose frontmost is true')
            app_name = front.stdout.strip() or "?"
            windows = _osascript(
                'tell application "System Events" to get name of windows of (first process whose frontmost is true)')
            win_list = [w.strip() for w in windows.stdout.split(",") if w.strip()][:5]
            return ToolResult(True, self.name,
                              message=f"Öndeki uygulama: {app_name}. Pencereler: {', '.join(win_list) or 'yok'}",
                              data={"app": app_name, "windows": win_list})
        except Exception as e:
            return ToolResult(False, self.name, error=f"Ekran bağlamı alınamadı: {e}")


class SetWatchTopicsTool(Tool):
    name = "watch_topics"
    description = (
        "Haber takibi (pano izleme) konularını ayarlar veya kapatır. 'teknoloji "
        "haberlerini takip et', 'yapay zeka ve uzay haberlerini izle', 'haber "
        "takibini kapat' gibi isteklerde kullanılır. Yeni haber gelince ELİŞA "
        "kullanıcıyı sesli uyarır.")
    parameters = {
        "type": "object",
        "properties": {
            "topics": {
                "type": "string",
                "description": "Virgülle ayrılmış konular (örn: 'teknoloji, yapay zeka'). Boş string = takibi kapat."
            }
        },
        "required": ["topics"],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from .. import settings as _settings
        raw = str((args or {}).get("topics", "")).strip()
        topics = [t.strip() for t in raw.split(",") if t.strip()][:5]
        _settings.set_many({"watch_topics": ", ".join(topics)})
        if topics:
            return ToolResult(True, self.name,
                              message=(f"Tamam, şunları takip ediyorum: "
                                       f"{', '.join(topics)}. Yeni haber gelince seni uyarırım."),
                              data={"topics": topics})
        return ToolResult(True, self.name, message="Haber takibini kapattım.")


class SystemLoadTool(Tool):
    name = "system_load"
    description = (
        "Mac'in anlık yükünü ve ısınma durumunu raporlar: CPU %, RAM %, termal "
        "durum. 'Mac ısındı mı', 'sistem yükü ne', 'bilgisayar kasıyor mu' gibi "
        "sorularda kullan.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from ..hw_monitor import get_status, check_once
        st = get_status()
        if not st.get("cpu"):
            st = check_once(speak_fn=None)
        cpu, ram = st.get("cpu", 0), st.get("ram", 0)
        thermal = st.get("thermal", "bilinmiyor")
        thermal_tr = {"normal": "normal ✓", "throttle": "KISITLANIYOR (ısınıyor!)",
                      "bilinmiyor": "bilinmiyor"}.get(thermal, thermal)
        if thermal == "throttle" or cpu >= 85:
            durum = "🔥 Makine zorlanıyor — ağır uygulamaları kapatmayı önerebilirim."
        elif cpu >= 50:
            durum = "Yük orta seviyede."
        else:
            durum = "Sistem serin ve rahat. ✓"
        return ToolResult(True, self.name,
                          message=(f"CPU %{cpu:.0f}, RAM %{ram:.0f}, termal: {thermal_tr}. {durum}"),
                          data={"cpu": cpu, "ram": ram, "thermal": thermal})


class AutostartTool(Tool):
    name = "autostart"
    description = (
        "ELİŞA'nın Mac açılışında otomatik başlatmasını açar/kapatır (macOS "
        "LaunchAgent). 'Açılışta otomatik başlasın' / 'otomatik başlatmayı kapat' "
        "gibi isteklerde kullanılır.")
    parameters = {
        "type": "object",
        "properties": {"enabled": {"type": "boolean",
                                   "description": "True=aç, False=kapat"}},
        "required": ["enabled"],
    }
    risk_level = RiskLevel.LOW
    PLIST_LABEL = "com.elisha.assistant"

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        import subprocess
        from pathlib import Path
        enable = bool((args or {}).get("enabled"))
        plist = Path.home() / "Library" / "LaunchAgents" / f"{self.PLIST_LABEL}.plist"
        root = Path(__file__).resolve().parents[2]
        cmd = str(root / "ELİŞA.command")
        try:
            if enable:
                if not Path(cmd).exists():
                    return ToolResult(False, self.name, error=f"Başlatıcı bulunamadı: {cmd}")
                plist.parent.mkdir(parents=True, exist_ok=True)
                plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{self.PLIST_LABEL}</string>
  <key>Program</key><string>{cmd}</string>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/elisha-app.log</string>
  <key>StandardErrorPath</key><string>/tmp/elisha-app.log</string>
</dict></plist>""")
                subprocess.run(["launchctl", "unload", str(plist)],
                               capture_output=True, timeout=8)
                r = subprocess.run(["launchctl", "load", str(plist)],
                                   capture_output=True, text=True, timeout=8)
                if r.returncode != 0:
                    return ToolResult(False, self.name,
                                      error=f"LaunchAgent yüklenemedi: {r.stderr[:120]}")
                return ToolResult(True, self.name,
                                  message="Tamam — artık Mac açılınca ELİŞA kendiliğinden başlayacak. "
                                          "Kapatmak istersen 'otomatik başlatmayı kapat' de.")
            # disable
            if plist.exists():
                subprocess.run(["launchctl", "unload", str(plist)],
                               capture_output=True, timeout=8)
                plist.unlink(missing_ok=True)
            return ToolResult(True, self.name,
                              message="Otomatik başlatma kapatıldı.")
        except Exception as e:
            return ToolResult(False, self.name, error=f"autostart hatası: {e}")
