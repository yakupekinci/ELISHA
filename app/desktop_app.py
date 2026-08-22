"""
ELİŞA — Siri tarzı gizli asistan (v3)
- Pencere GİZLİ başlar, menü bar ikonundan veya 'hey elişa uyan' ile açılır
- 60sn hareketsizlikte kendini gizler (keep_alive JS çağrısı uzatır)
- X simgesi: gizle | - simgesi: gizle (pencereyi kapatmaz, background'da çalışmaya devam)
Çalıştır: python3 app/desktop_app.py
"""
import threading, time, subprocess, sys, json, urllib.request, os, atexit
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# venv python'u tespit et (sistem Python yerine venv'in kendi Python'unu kullan)
_VENV_PY = ROOT / "venv" / "bin" / "python3"
PYTHON = str(_VENV_PY) if _VENV_PY.exists() else sys.executable

# ── Tek instance kilidi ────────────────────────────────────────────────────
_APP_LOCK = Path("/tmp/elisha_app.pid")

def _acquire_lock():
    if _APP_LOCK.exists():
        try:
            pid = int(_APP_LOCK.read_text().strip())
            os.kill(pid, 0)
            print(f"⚠️  ELİŞA zaten çalışıyor (PID {pid}). Çıkılıyor.")
            sys.exit(0)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    _APP_LOCK.write_text(str(os.getpid()))
    atexit.register(lambda: _APP_LOCK.unlink(missing_ok=True))

_acquire_lock()

# ── Ollama otomatik başlatma ───────────────────────────────────────────────
def _ensure_ollama():
    """Ollama çalışmıyorsa başlat; max 20sn bekle."""
    import shutil

    def _is_running() -> bool:
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
            return True
        except Exception:
            return False

    if _is_running():
        print("✅ Ollama zaten çalışıyor.")
        return True

    print("🚀 Ollama başlatılıyor...")

    # macOS app Resources binary'si en güvenilir yol (GUI wrapper çöküyor)
    _resources_bin = "/Applications/Ollama.app/Contents/Resources/ollama"
    _started = False
    if Path(_resources_bin).exists():
        try:
            subprocess.Popen(
                [_resources_bin, "start"],
                stdout=open("/tmp/ollama.log", "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "OLLAMA_DEBUG": "0"})
            print(f"   {_resources_bin} start başlatıldı")
            _started = True
        except Exception as e:
            print(f"   Resources binary başlatılamadı: {e}")

    # Resources yoksa standart CLI dene (serve yerine start)
    if not _started:
        for candidate in [
            str(Path.home() / ".local/bin/ollama"),
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",
        ]:
            if Path(candidate).exists():
                try:
                    subprocess.Popen(
                        [candidate, "start"],
                        stdout=open("/tmp/ollama.log", "a"),
                        stderr=subprocess.STDOUT,
                        start_new_session=True)
                    print(f"   {candidate} start başlatıldı")
                    break
                except Exception as e:
                    print(f"   {candidate} başlatılamadı: {e}")

    # API hazır olana kadar bekle (max 20sn)
    for i in range(40):
        if _is_running():
            print(f"✅ Ollama hazır ({(i+1)*0.5:.1f}sn)")
            return True
        time.sleep(0.5)
        if i % 8 == 7:
            print("   Bekleniyor...")

    print("⚠️  Ollama 20sn içinde açılmadı — LLM mock modda çalışacak.")
    return False

# Arka planda başlat (server başlamayı engellemesin)
_ollama_thread = threading.Thread(target=_ensure_ollama, daemon=True)
_ollama_thread.start()

# ── Dosya tabanlı IPC ─────────────────────────────────────────────────────
WAKE_FILE   = Path("/tmp/elisha_wake")
HIDE_FILE   = Path("/tmp/elisha_hide")
ENABLE_FILE = Path("/tmp/elisha_wake_enabled")
ENABLE_FILE.write_text("1")

# ── HTTP sunucu ────────────────────────────────────────────────────────────
def start_server():
    from http.server import ThreadingHTTPServer
    from app.server import Handler
    httpd = ThreadingHTTPServer(("", 8765), Handler)
    httpd.daemon_threads = True
    print("server :8765")
    httpd.serve_forever()

threading.Thread(target=start_server, daemon=True).start()

def wait_server(timeout=40):
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen("http://localhost:8765/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False

if not wait_server():
    print("server açılamadı!"); sys.exit(1)
print("server hazır")

# ── Alt süreçler ───────────────────────────────────────────────────────────
subprocess.Popen(
    [PYTHON, "-u", "app/wake_daemon.py"], cwd=str(ROOT),
    stdout=open("/tmp/wake.log", "a"), stderr=subprocess.STDOUT,
    start_new_session=True)
print("wake daemon başladı")

subprocess.Popen(
    [PYTHON, "-u", "app/menubar.py"], cwd=str(ROOT),
    stdout=open("/tmp/menubar.log", "a"), stderr=subprocess.STDOUT,
    start_new_session=True)
print("menü bar başladı")

# ── Dock ikonunu gizle (macOS) ─────────────────────────────────────────────
if sys.platform == "darwin":
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or \
               NSBundle.mainBundle().infoDictionary()
        if info:
            info["LSUIElement"] = "1"
    except Exception:
        pass

# ── Durum ──────────────────────────────────────────────────────────────────
import webview
STATE = {"visible": False, "last": 0, "window_ready": False}
window = None  # sonra atanacak

# ── JS API köprüsü ─────────────────────────────────────────────────────────
class ElishaApi:
    """pywebview.api üzerinden JS'e açılan Python metotları."""

    # Pencereyi gizle — X ve − butonları her ikisi de buraya bağlı
    def hide_app(self):
        threading.Thread(target=do_hide, daemon=True).start()
        return "ok"

    # winClose() ve winMinimize() de hide_app çağırır (uygulama arka planda devam eder)
    def close(self):
        threading.Thread(target=do_hide, daemon=True).start()
        return "ok"

    def minimize(self):
        threading.Thread(target=do_hide, daemon=True).start()
        return "ok"

    # Hareketsizlik sayacını sıfırla (her 5sn JS'den çağrılır)
    def keep_alive(self):
        STATE["last"] = time.time()
        return "ok"

    # Sayfa geçişleri
    def switch_to_overlay(self):
        try: window.load_url("http://localhost:8765/overlay.html")
        except Exception: pass
        return "ok"

    def switch_to_fullscreen(self):
        try: window.load_url("http://localhost:8765/fullscreen.html")
        except Exception: pass
        return "ok"

    # Sunucu durumunu çek
    def get_status(self):
        try:
            import urllib.request as _ur, json as _js
            r = _ur.urlopen("http://localhost:8765/api/status", timeout=2)
            return _js.loads(r.read())
        except Exception:
            return {}

# ── Pencere ────────────────────────────────────────────────────────────────
try:
    import AppKit as _AK
    _screen = _AK.NSScreen.mainScreen().frame()
    _W, _H = int(_screen.size.width), int(_screen.size.height)
except Exception:
    _W, _H = 1440, 900

window = webview.create_window(
    "ELİŞA",
    "http://localhost:8765/fullscreen.html",
    width=_W, height=_H,
    frameless=True,
    on_top=True,
    hidden=True,
    transparent=False,
    easy_drag=False,
    background_color="#050508",
    js_api=ElishaApi(),
)

# ── Göster / Gizle ────────────────────────────────────────────────────────
def do_hide():
    try: window.hide()
    except Exception: pass
    STATE["visible"] = False

def do_show(reason: str = ""):
    try: window.move(0, 0)
    except Exception: pass
    try: window.show()
    except Exception: pass
    STATE["visible"] = True
    STATE["last"] = time.time()
    if reason and STATE["window_ready"]:
        # Yeni fullscreen.html'deki state machine'e wake eventi gönder
        _js = f"""
        (function() {{
            if (typeof setState === 'function') {{
                setState('listening');
            }}
            if (typeof startListen === 'function') {{
                startListen();
            }}
            if (typeof showToast === 'function') {{
                showToast('Hey ELİŞA!');
            }}
            if (typeof ELISHA_EXTERNAL_WAKE === 'function') {{
                ELISHA_EXTERNAL_WAKE({json.dumps(reason)});
            }}
        }})();
        """
        try: window.evaluate_js(_js)
        except Exception as e: print(f"js wake: {e}")

def on_loaded():
    STATE["window_ready"] = True
    print("panel hazır (gizli başladı)")

window.events.loaded += on_loaded

# ── Poll döngüsü ──────────────────────────────────────────────────────────
def poll():
    while True:
        try:
            if HIDE_FILE.exists():
                try: HIDE_FILE.unlink()
                except Exception: pass
                do_hide()
            elif WAKE_FILE.exists() and ENABLE_FILE.exists():
                try:
                    txt = WAKE_FILE.read_text().strip()
                    WAKE_FILE.unlink()
                except Exception:
                    txt = "wake"
                print(f"✨ wake: {txt}")
                do_show(txt)
            # 60sn hareketsizlikte otomatik gizle
            if STATE["visible"] and (time.time() - STATE["last"]) > 60:
                do_hide()
        except Exception as e:
            print(f"poll: {e}")
        time.sleep(0.4)

threading.Thread(target=poll, daemon=True).start()

print("✨ ELİŞA gizli modda — menü çubuğundaki ikona bas veya 'hey elişa uyan' de")

# ── Dock gizle (pywebview başladıktan sonra) ───────────────────────────────
def _post_start():
    time.sleep(0.3)
    try:
        import AppKit
        AppKit.NSApp.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

webview.start(func=_post_start, debug=False)
