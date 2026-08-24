"""ELİŞA Donanım İzleme — Mark-LI 'Hardware Monitoring' esinli.
CPU/RAM yükünü ve macOS termal durumunu izler; makine zorlanınca SESLI uyarır
(kullanıcı ısıya hassas — fansız MacBook Air). psutil + pmset, root gerekmez.

Ayarlar: hw_alerts (true/false, varsayılan açık)
"""
import threading
import time

from . import settings
from .log import log

_thread = None
_state = {"cpu_hi_streak": 0, "last_alert": 0.0, "last": {"cpu": 0, "ram": 0, "thermal": "bilinmiyor"}}
_lock = threading.Lock()

ALERT_COOLDOWN = 15 * 60   # aynı uyarı en fazla 15 dk'da bir
CPU_HI = 85                # % üstü = yüksek
STREAK_NEED = 3            # 3 ardışık ölçüm (3x ~60sn)


def _thermal() -> str:
    """macOS termal baskı durumu: 'normal' | 'throttle' | 'bilinmiyor'."""
    try:
        import subprocess
        r = subprocess.run(["pmset", "-g", "therm"], capture_output=True,
                           text=True, timeout=6)
        out = (r.stdout or "").lower()
        if "no thermal warning" in out and "no cpu power status" in out:
            return "normal"
        if "cpu_speed_limit" in out or "thermal warning" in out:
            # CPU_Speed_Limit=50 gibi satır → kısıtlanıyor = ısınıyor
            import re
            m = re.search(r"cpu_speed_limit\s*=\s*(\d+)", out)
            if m and int(m.group(1)) < 100:
                return "throttle"
            if "thermal warning" in out and "no thermal warning" not in out:
                return "throttle"
            return "normal"
        return "bilinmiyor"
    except Exception:
        return "bilinmiyor"


def check_once(speak_fn=None) -> dict:
    """Bir ölçüm turu: cpu/ram/termal + gerekirse sesli uyarı."""
    cpu, ram = 0, 0
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
    except Exception:
        pass
    thermal = _thermal()
    with _lock:
        _state["last"] = {"cpu": cpu, "ram": ram, "thermal": thermal}
        if str(settings.get("hw_alerts", True)) in ("0", "false", "False", ""):
            return _state["last"]
        hot = thermal == "throttle" or cpu >= CPU_HI
        if hot:
            _state["cpu_hi_streak"] += 1
        else:
            _state["cpu_hi_streak"] = 0
        should = (_state["cpu_hi_streak"] >= STREAK_NEED or thermal == "throttle") \
                 and (time.time() - _state["last_alert"] > ALERT_COOLDOWN)
        if should and speak_fn:
            _state["last_alert"] = time.time()
            _state["cpu_hi_streak"] = 0
            msg = ("Mac'in biraz ısındı gibi — fanı olmayan model olduğu için "
                   "biraz dinlendirebiliriz. İstersen ağır programları kapatayım.")
            try:
                speak_fn(msg)
                log("HW", f"🔥 uyarı verildi (cpu={cpu:.0f}%, termal={thermal})")
            except Exception:
                pass
    return _state["last"]


def get_status() -> dict:
    with _lock:
        return dict(_state["last"])


def _loop(speak_fn):
    import psutil  # prime cpu_percent
    psutil.cpu_percent(interval=None)
    time.sleep(2)
    while True:
        try:
            check_once(speak_fn)
        except Exception as e:
            log("HW", f"izleme hatası: {e}")
        time.sleep(60)


def start(speak_fn):
    global _thread
    if _thread is not None:
        return
    _thread = threading.Thread(target=_loop, args=(speak_fn,), daemon=True)
    _thread.start()
    log("HW", "📊 donanım izleme başladı (CPU/RAM/termal, 60sn)")
