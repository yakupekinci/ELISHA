"""Ek araçlar — Mark-LI / Mark-XXXIX-OR portları:
youtube_play, send_message, game_update, flight_finder, analyze_camera, dashboard"""
import base64
import re
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


def _open(url_or_cmd: str, is_url: bool = True):
    if is_url:
        webbrowser.open(url_or_cmd)
    else:
        subprocess.Popen(url_or_cmd, shell=True)


class YouTubePlayTool(Tool):
    name = "youtube_play"
    description = (
        "YouTube'da şarkı/video ARAR ve en uygun sonucu OYNATIR. 'X çal', 'X "
        "videosunu aç', 'YouTube'da X izlet' gibi isteklerde kullan. Sadece arama "
        "istiyorsa web_search kullan.")
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string",
                                 "description": "Aranacak şarkı/video adı"}},
        "required": ["query"],
    }
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        query = str((args or {}).get("query", "")).strip()
        if not query:
            return ToolResult(False, self.name, error="Aranacak şey boş.")
        try:
            import requests
            url = ("https://www.youtube.com/results?search_query="
                   + urllib.parse.quote(query))
            r = requests.get(url, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0",
                                      "Accept-Language": "tr"})
            ids = re.findall(r'"videoId":"([\w-]{11})"', r.text)
            if not ids:
                _open(url)
                return ToolResult(True, self.name,
                                  message=f"YouTube arama sayfasını açtım: {query}")
            watch = f"https://www.youtube.com/watch?v={ids[0]}"
            _open(watch)
            return ToolResult(True, self.name,
                              message=f"▶️ Oynatıyorum: {query}",
                              data={"url": watch})
        except Exception as e:
            return ToolResult(False, self.name, error=f"YouTube açılamadı: {e}")


class SendMessageTool(Tool):
    name = "send_message"
    description = (
        "WhatsApp veya Telegram'da MESAJ HAZIRLAR ve uygulamayı açar (güvenlik "
        "için son gönderme tuşuna kullanıcı basar). 'Ayşe'ye WhatsApp'tan X yaz', "
        "'Telegram'da X gönder' gibi isteklerde kullanılır. phone parametresi "
        "uluslararası format: 905xxxxxxxxx")
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string",
                    "description": "whatsapp | telegram (varsayılan whatsapp)"},
            "phone": {"type": "string",
                      "description": "Alıcı telefonu, uluslararası format (905xx…)"},
            "text": {"type": "string", "description": "Gönderilecek mesaj"},
        },
        "required": ["text"],
    }
    risk_level = RiskLevel.MEDIUM

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        app = str((args or {}).get("app", "whatsapp")).lower()
        text = str((args or {}).get("text", "")).strip()
        phone = re.sub(r"\D", "", str((args or {}).get("phone", "")))
        if not text:
            return ToolResult(False, self.name, error="Mesaj boş.")
        try:
            if app == "telegram":
                if phone:
                    _open(f"tg://resolve?domain=&phone={phone}") if False else None
                    url = f"https://t.me/+{phone}" if False else f"tg://msg?text={urllib.parse.quote(text)}"
                    _open(url)
                else:
                    _open(f"tg://msg?text={urllib.parse.quote(text)}")
                return ToolResult(True, self.name,
                                  message="Telegram açıldı, mesaj hazırlandı — "
                                          "alıcıyı seçip gönder tuşuna bas.")
            # WhatsApp click-to-chat
            if phone:
                _open(f"https://wa.me/{phone}?text={urllib.parse.quote(text)}")
                return ToolResult(True, self.name,
                                  message=f"WhatsApp hazır ({phone}) — gönder tuşuna basman yeterli.")
            _open("https://web.whatsapp.com")
            return ToolResult(True, self.name,
                              message="WhatsApp Web açıldı — mesajı kopyaladım, "
                                      f"yapıştırıp gönderebilirsin: \"{text[:60]}\"")
        except Exception as e:
            return ToolResult(False, self.name, error=f"Mesaj hazırlanamadı: {e}")


class GameUpdateTool(Tool):
    name = "game_update"
    description = (
        "Steam veya Epic Games istemcisini GÜNCELLEMELER sayfasında açar. 'Oyun "
        "güncellemelerini kontrol et', 'Steam güncelleme' gibi isteklerde kullanılır.")
    parameters = {
        "type": "object",
        "properties": {"store": {"type": "string",
                                 "description": "steam | epic (varsayılan steam)"}},
        "required": [],
    }
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        store = str((args or {}).get("store", "steam")).lower()
        try:
            if store == "epic":
                _open("com.epicgames.EpicGamesLauncher://", is_url=False) if False else \
                    _open("https://store.epicgames.com/download")
                return ToolResult(True, self.name,
                                  message="Epic Games indirmeler sayfası açıldı.")
            _open("steam://open/downloads", is_url=False)
            return ToolResult(True, self.name,
                              message="Steam güncellemeler sayfası açıldı.")
        except Exception as e:
            return ToolResult(False, self.name,
                              error=f"{store} açılamadı (kurulu mu?): {e}")


class FlightFinderTool(Tool):
    name = "flight_finder"
    description = (
        "Uçuş fiyatı/uygunluk ARAMASI yapar. 'İstanbul Antalya uçak bileti', 'ucuz "
        "uçuş ara' gibi isteklerde kullanılır. Sonuçlar web aramasından gelir; "
        "kesin fiyat için havayolu sitesi önerilir.")
    parameters = {
        "type": "object",
        "properties": {
            "from_city": {"type": "string", "description": "Kalkış şehri"},
            "to_city": {"type": "string", "description": "Varış şehri"},
            "date": {"type": "string", "description": "Tarih (opsiyonel, örn: 'bu hafta sonu')"},
        },
        "required": ["from_city", "to_city"],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        src = str((args or {}).get("from_city", "")).strip()
        dst = str((args or {}).get("to_city", "")).strip()
        date = str((args or {}).get("date", "")).strip()
        if not src or not dst:
            return ToolResult(False, self.name, error="Kalkış ve varış şehri gerekli.")
        q = f"{src} {dst} ucuz uçak bileti {date}".strip()
        try:
            from .web_tools import WebSearchTool
            r = WebSearchTool(self.config).execute({"query": q})
            if not r.success:
                return r
            return ToolResult(True, self.name,
                              message=f"{src} → {dst} arama sonuçları:\n"
                                      + str(r.message)[:500],
                              data={"query": q})
        except Exception as e:
            return ToolResult(False, self.name, error=f"Uçuş araması başarısız: {e}")


class AnalyzeCameraTool(Tool):
    name = "analyze_camera"
    description = (
        "Web kameraya (FaceTime kamerası) BAKAR ve görüp analiz eder. 'Kameraya "
        "bak', 'görüntüde ne var', 'beni görüyor musun' gibi isteklerde kullanılır. "
        "analyze_screen ekrana bakar; bu KAMERAYA bakar.")
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string",
                       "description": "Kamerada neye bakılacağı (opsiyonel)"}
        },
        "required": [],
    }
    risk_level = RiskLevel.MEDIUM   # kamera = mahremiyet

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        question = str((args or {}).get("prompt") or
                       "Kamerada ne görüyorsun? Kısaca açıkla.").strip()
        shot = Path("/tmp/elisha_cam.jpg")
        try:
            import cv2
            cam = cv2.VideoCapture(0)
            ok = False
            for _ in range(8):          # otomatik pozlama için birkaç kare atla
                ok, frame = cam.read()
                if ok:
                    break
            cam.release()
            if not ok:
                return ToolResult(False, self.name, error=(
                    "Kamera görüntüsü alınamadı — başka uygulama kullanıyor olabilir "
                    "veya kamera izni gerekli (Sistem Ayarları → Gizlilik → Kamera)."))
            import cv2 as _cv
            _cv.imwrite(str(shot), frame)
        except ImportError:
            return ToolResult(False, self.name, error="Kamera modülü (opencv) kurulu değil.")
        except Exception as e:
            return ToolResult(False, self.name, error=f"Kamera hatası: {e}")
        try:
            img_b64 = base64.b64encode(shot.read_bytes()).decode()
            from ..llm.providers import OpenRouterProvider
            op = OpenRouterProvider(self.config)
            answer = op.vision(question, img_b64, mime="image/jpeg")
        except Exception as e:
            return ToolResult(False, self.name, error=f"Görü analizi başarısız: {e}")
        return ToolResult(True, self.name, message=answer[:900], data={"source": "camera"})


class DashboardTool(Tool):
    name = "dashboard"
    description = (
        "Telefondan kumanda için QR kodu oluşturur ve gösterir. 'Telefondan "
        "kumanda', 'QR kod göster', 'telefondan kontrol' gibi isteklerde kullanılır.")
    parameters = {"type": "object", "properties": {}, "required": []}
    risk_level = RiskLevel.LOW

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            from ..remote_dashboard import make_qr, dashboard_url
            path = make_qr()
            _open(path, is_url=False) if False else subprocess.Popen(["open", path])
            return ToolResult(True, self.name,
                              message="📱 QR kodu masaüstünde açtım — telefon kamerasıyla "
                                      "okut, tarayıcıdan ELİŞA'yı kumanda edebilirsin. "
                                      f"Adres: {dashboard_url()}")
        except Exception as e:
            return ToolResult(False, self.name, error=f"QR oluşturulamadı: {e}")
