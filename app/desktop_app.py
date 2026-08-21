"""
ELİŞA — Siri tarzı gizli asistan (v2)
- Pencere GİZLİ başlar, menü bar ✦ ikonundan veya 'hey elişa uyan' ile açılır
- 15sn hareketsizlikte kendini gizler
Çalıştır: python3 app/desktop_app.py
"""
import threading, time, subprocess, sys, json, urllib.request
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

WAKE_FILE = Path("/tmp/elisha_wake")
HIDE_FILE = Path("/tmp/elisha_hide")
ENABLE_FILE = Path("/tmp/elisha_wake_enabled")
ENABLE_FILE.write_text("1")

# ---------- SERVER ----------
def start_server():
    from http.server import ThreadingHTTPServer
    from app.server import Handler
    httpd = ThreadingHTTPServer(("", 8765), Handler)
    httpd.daemon_threads = True
    print("server :8765")
    httpd.serve_forever()

threading.Thread(target=start_server, daemon=True).start()

def wait_server(timeout=40):
    for _ in range(timeout*2):
        try:
            urllib.request.urlopen("http://localhost:8765/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False

if not wait_server():
    print("server açılamadı!"); sys.exit(1)
print("server hazır")

# ---------- WAKE DAEMON ----------
subprocess.Popen(["python3","-u","app/wake_daemon.py"], cwd=str(ROOT),
                 stdout=open("/tmp/wake.log","a"), stderr=subprocess.STDOUT,
                 start_new_session=True)
print("wake daemon başladı")

# ---------- MENÜ BAR (ayrı süreç) ----------
subprocess.Popen(["python3","-u","app/menubar.py"], cwd=str(ROOT),
                 stdout=open("/tmp/menubar.log","a"), stderr=subprocess.STDOUT,
                 start_new_session=True)
print("menü bar başladı")

# ---------- WEBVIEW (ANA THREAD) ----------
import webview

# macOS: Dock'ta Python ikonu GÖSTERMEMELİ
import sys
if sys.platform == "darwin":
    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info:
            info["LSUIElement"] = "1"
    except Exception:
        pass

STATE = {"visible": False, "last": 0}

def js_api():
    class Api:
        def hide_app(self):
            do_hide()
            return "ok"
        def keep_alive(self):
            STATE["last"] = time.time()
            return "ok"
    return Api()

# Masaüstü overlay — şeffaf, çerçevesiz, her zaman üstte, GİZLİ BAŞLAR
window = webview.create_window(
    "ELİŞA",
    "http://localhost:8765/overlay.html",
    width=380, height=560,
    frameless=True,
    on_top=True,
    hidden=True,
    transparent=True,
    easy_drag=True,
    background_color="#000000",
    js_api=js_api(),
)

def do_hide():
    try: window.hide()
    except: pass
    STATE["visible"] = False

def do_show(reason=""):
    try:
        import AppKit
        f = AppKit.NSScreen.mainScreen().frame()
        # Sağ alt köşede, dock'un üstünde
        x = int(f.size.width - 400)
        y = int(f.size.height - 600)
        window.move(x, y)
    except Exception:
        pass
    window.show()
    STATE["visible"] = True
    STATE["last"] = time.time()
    if reason:
        try:
            window.evaluate_js(f"ELISHA_EXTERNAL_WAKE && ELISHA_EXTERNAL_WAKE({json.dumps(reason)})")
        except Exception as e:
            print(f"js: {e}")

def on_loaded():
    # Panel hazır ama GİZLİ KALACAK — sadece wake/menubar açar
    print("panel hazır (gizli başladı)")

window.events.loaded += on_loaded

def poll():
    while True:
        try:
            if HIDE_FILE.exists():
                HIDE_FILE.unlink(); do_hide()
            elif WAKE_FILE.exists() and ENABLE_FILE.exists():
                txt = WAKE_FILE.read_text().strip(); WAKE_FILE.unlink()
                print(f"✨ wake: {txt}")
                do_show(txt)
            if STATE["visible"] and time.time()-STATE["last"] > 60:
                do_hide()
        except Exception as e:
            print(f"poll: {e}")
        time.sleep(0.4)

threading.Thread(target=poll, daemon=True).start()

print("✨ ELISHA gizli modda — menü çubuğundaki ✦'a bas veya 'hey elişa uyan' de")

def _hide_dock():
    """pywebview başladıktan sonra dock ikonunu gizle"""
    import time as _t; _t.sleep(0.3)
    try:
        import AppKit
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

webview.start(func=_hide_dock, debug=False)
