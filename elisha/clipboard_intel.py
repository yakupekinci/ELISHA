"""ELİŞA Pano Zekası — Mark-LI 'Clipboard Intelligence' esinli.
Kullanıcı bir metin kopyaladığında yakalar; HUD'da Çevir/Özetle/Açıkla/Düzelt
çipleri gösterilir. Gizlilik: içerik MAC'TEN ÇIKMAZ, sadece uzunluk/hash loglanır.

Ayarlar: clipboard_intel (varsayılan açık), min uzunluk 40 karakter.
"""
import threading

from . import settings
from .log import log

_thread = None
_pending = {"hash": "", "text": "", "ts": 0}
_lock = threading.Lock()


def _read_clipboard() -> str:
    try:
        import subprocess
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def pop_pending() -> dict:
    with _lock:
        if _pending["hash"] and _pending["text"]:
            out = dict(_pending)
            _pending["hash"] = ""       # bir kez göster
            _pending["text"] = ""
            return out
    return {}


def _loop():
    last_hash = ""
    import hashlib
    while True:
        try:
            if str(settings.get("clipboard_intel", True)) in ("0", "false", "False"):
                time_sleep(4)
                continue
            text = _read_clipboard()
            if text and len(text) >= 40:
                h = hashlib.md5(text.encode()).hexdigest()[:12]
                if h != last_hash:
                    last_hash = h
                    with _lock:
                        _pending.update({"hash": h, "text": text[:1500],
                                         "ts": time_time()})
                    log("CLIP", f"📋 yeni metin yakalandı ({len(text)} kr) — "
                                f"içerik gizli, cihazda kalır")
        except Exception:
            pass
        time_sleep(3)


def time_time():
    import time
    return time.time()


def time_sleep(s):
    import time
    time.sleep(s)


def start():
    global _thread
    if _thread is not None:
        return
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    log("CLIP", "📋 pano zekası başladı (kopyala → HUD'da Çevir/Özetle/Açıkla/Düzelt)")
