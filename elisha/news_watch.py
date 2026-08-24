"""ELİŞA Pano İzleme — Mark-LI 'Background Monitoring' esinli.
Kullanıcının seçtiği konuları (örn: 'teknoloji, yapay zeka') periyodik olarak
Google News RSS üzerinden kontrol eder; YENİ başlık varses bir kez sesli +
sohbet logunda bildirir.

Ayarlar (settings):
  watch_topics: "yapay zeka, teknoloji"  (boş = kapalı)
  watch_interval_min: dakika cinsinden aralık (varsayılan 240)
"""
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import settings
from .log import log

_SEEN_PATH = Path("/tmp/elisha_watch_seen.json")
_thread = None
_pending = []          # bildirilecek yeni başlıklar (HUD bir kez gösterir)
_pending_lock = threading.Lock()


def _fetch_titles(topic: str, limit: int = 3):
    import requests
    url = (f"https://news.google.com/rss/search?q={topic}"
           f"&hl=tr&gl=TR&ceid=TR:tr")
    r = requests.get(url, timeout=8, headers={"User-Agent": "curl/8"})
    root = ET.fromstring(r.content)
    out = []
    for item in root.findall(".//item/title")[:limit]:
        if item.text:
            out.append(item.text.strip())
    return out


def _load_seen() -> dict:
    import json
    try:
        return json.loads(_SEEN_PATH.read_text())
    except Exception:
        return {}


def _save_seen(seen: dict):
    import json
    try:
        _SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False))
    except Exception:
        pass


def check_once(speak_fn=None) -> list:
    """Tüm konuları bir kez kontrol et; yeni başlıkları döndür (+bildir)."""
    topics = [t.strip() for t in
              str(settings.get("watch_topics") or "").split(",")
              if t.strip()]
    if not topics:
        return []
    seen = _load_seen()
    fresh = []
    for topic in topics[:5]:
        try:
            for title in _fetch_titles(topic):
                key = title[:120]
                if seen.get(key):
                    continue
                seen[key] = time.time()
                fresh.append((topic, title))
        except Exception as e:
            log("WATCH", f"'{topic}' kontrol hatası: {e}")
    # 200 kayıt üstü birikmesin
    if len(seen) > 200:
        for k in sorted(seen, key=seen.get)[:len(seen) - 200]:
            seen.pop(k, None)
    _save_seen(seen)
    if fresh and speak_fn:
        lines = "\n".join(f"• {t}" for _, t in fresh[:4])
        spoken = (f"Takip ettiğin konularda yeni haberler var: "
                  + ". ".join(t for _, t in fresh[:3]))
        try:
            speak_fn(spoken)
        except Exception:
            pass
        with _pending_lock:
            _pending.extend(f"[{topic}] {title}" for topic, title in fresh[:6])
    if fresh:
        log("WATCH", f"🔔 {len(fresh)} yeni başlık: {fresh[0][1][:70]}")
    return fresh


def _loop(speak_fn):
    while True:
        try:
            interval = float(settings.get("watch_interval_min") or 240)
        except (TypeError, ValueError):
            interval = 240
        interval = max(30, interval)
        try:
            if settings.get("watch_topics"):
                check_once(speak_fn)
        except Exception as e:
            log("WATCH", f"döngü hatası: {e}")
        time.sleep(interval * 60)


def start(speak_fn):
    """Server'dan bir kez çağrılır — arka plan izleme thread'i başlatır."""
    global _thread
    if _thread is not None:
        return
    _thread = threading.Thread(target=_loop, args=(speak_fn,), daemon=True)
    _thread.start()
    log("WATCH", f"👁️ pano izleme başladı (konular: "
                 f"{settings.get('watch_topics') or 'yok — ayarlardan ekle'})")


def pop_pending() -> list:
    """HUD bir kez alır, sonra temizlenir."""
    with _pending_lock:
        out, _pending[:] = list(_pending), []
        return out
