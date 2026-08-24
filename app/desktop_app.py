"""
ELİŞA — Siri tarzı gizli asistan (v3)
- Pencere GİZLİ başlar, menü bar ikonundan veya 'hey elişa uyan' ile açılır
- 60sn hareketsizlikte kendini gizler (keep_alive JS çağrısı uzatır)
- X simgesi: gizle | - simgesi: gizle (pencereyi kapatmaz, background'da çalışmaya devam)
Çalıştır: python3 app/desktop_app.py
"""
import threading, time, subprocess, sys, json, urllib.request, os, atexit, signal
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Temiz çıkış: launchd KeepAlive(SuccessfulExit=false) crash'de diriltir,
#    düzgün çıkışta (exit 0) dokunmaz. SIGTERM = kullanıcı kapattı demektir.
_QUIT_FLAG = Path("/tmp/elisha_quit")
try: _QUIT_FLAG.unlink(missing_ok=True)  # önceki oturumdan kalıntı varsa temizle
except Exception: pass

def _graceful_exit(*_a):
    try: _APP_LOCK.unlink(missing_ok=True)
    except Exception: pass
    # Menü bar da kapansın (tam kapanış)
    try: subprocess.run(["pkill", "-f", "app/menubar.py"], capture_output=True, timeout=5)
    except Exception: pass
    print("👋 ELİŞA kapanıyor (temiz çıkış)")
    # NOT: sys.exit() Cocoa event loop içinde NSException→abort(134) olur,
    # launchd bunu crash sanıp diriltir. os._exit kod 0 ile garantili çıkar.
    os._exit(0)

signal.signal(signal.SIGTERM, _graceful_exit)
signal.signal(signal.SIGINT, _graceful_exit)

# ── API anahtarlarını güvenli dosyadan yükle ───────────────────────────────
_secrets_file = Path.home() / ".config" / "elisha" / "secrets.env"
if _secrets_file.exists():
    for line in _secrets_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and value:
                os.environ[key] = value

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
        # ELİŞA.command zaten kontrol edip yazdı — sessizce onayla
        # (çift "zaten çalışıyor" mesajını önler)
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
    try:
        from app.server import ensure_mic_monitor
        ensure_mic_monitor()          # UI küre animasyonu için canlı RMS
    except Exception:
        pass                          # monitör kritik değil
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

# ── Dock ikonunu ayarla (macOS) ────────────────────────────────────────────
# Not: NSApp ancak event loop başladıktan sonra mevcut, _post_start'ta ayarlanacak

# ── Durum ──────────────────────────────────────────────────────────────────
import webview
STATE = {"visible": False, "last": 0, "window_ready": False}
window = None  # sonra atanacak

# ── JS API köprüsü ─────────────────────────────────────────────────────────
def _request_tcc_perms():
    """macOS Kamera iznini GUI sürecinden iste — diyalog pencerenin üstünde çıkar."""
    def work():
        try:
            import AVFoundation as AV
            st = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
            if st != 3:  # izinli değilse diyalog açılır
                AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AV.AVMediaTypeVideo,
                    lambda g: print(f"[TCC] kamera yanıtı: {g}"))
        except Exception as e:
            print(f"[TCC] kamera isteği hatası: {e}")
    import threading
    threading.Thread(target=work, daemon=True).start()


def _retry_cam_if_denied(granted):
    """Diyalog bastırıldıysa (False ama durum hâlâ 'belirlenmedi') 8sn sonra tekrar dene."""
    def work():
        time.sleep(8)
        try:
            import AppKit, AVFoundation as AV
            st = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
            if st == 3 or granted:
                return
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            print("[TCC] tekrar deneniyor — diyaloğu görüp 'İzin Ver'e bas")
            AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AV.AVMediaTypeVideo, lambda g: print(f"[TCC] kamera yanıtı(2): {g}"))
        except Exception as e:
            print(f"[TCC] yeniden deneme hatası: {e}")
    import threading
    threading.Thread(target=work, daemon=True).start()


class ElishaApi:
    """pywebview.api üzerinden JS'e açılan Python metotları."""

    # Pencereyi gizle — X ve − butonları her ikisi de buraya bağlı
    def hide_app(self):
        threading.Thread(target=do_hide, daemon=True).start()
        return "ok"

    # Kamera izni — JS'ten (kullanıcı tıklamasıyla) çağrılır
    def request_cam(self):
        def work():
            try:
                import AppKit
                import AVFoundation as AV
                st = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
                if st == 3:
                    print("[TCC] kamera zaten izinli")
                    return
                AppKit.NSApp.activateIgnoringOtherApps_(True)
                AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AV.AVMediaTypeVideo,
                    lambda g: print(f"[TCC] kamera yanıtı(tık): {g}"))
            except Exception as e:
                print(f"[TCC] istek hatası: {e}")
        threading.Thread(target=work, daemon=True).start()
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

    # ── Pencere sürükleme (frameless başlıksız pencere) ──
    def drag(self, dx: float, dy: float):
        try:
            window.move(int(window.x + dx), int(window.y + dy))
        except Exception:
            pass
        return "ok"

    def save_pos(self):
        try:
            import json as _json
            _json.dump({"x": window.x, "y": window.y},
                       open("/tmp/elisha_window.json", "w"))
        except Exception:
            pass
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

    # Wake tek tüketici: server /api/wake_check dosyayı tüketir ve JS tetikler;
    # bu metot sadece pencereyi öne getirir (JS enjeksiyonu yok → çift startListen olmaz)
    def wake_show(self):
        threading.Thread(target=do_show, args=("",), daemon=True).start()
        return "ok"

# ── Pencere ────────────────────────────────────────────────────────────────
try:
    import AppKit as _AK
    _screen = _AK.NSScreen.mainScreen().frame()
    _W, _H = int(_screen.size.width), int(_screen.size.height)
except Exception:
    _W, _H = 1440, 900

# Splash: siyah ekran + yükleniyor animasyonu (beyaz sayfa olmasın)
_SPLASH_HTML = """
<html><head><style>
html,body{margin:0;padding:0;width:100%;height:100%;background:#050510;overflow:hidden}
.c{display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column}
.eye{width:80px;height:80px;border-radius:50%;border:3px solid #00d4ff;animation:pulse 1.5s infinite;box-shadow:0 0 30px #00d4ff44}
@keyframes pulse{0%,100%{opacity:0.4;transform:scale(0.95)}50%{opacity:1;transform:scale(1.05)}}
.t{color:#6e7ea0;font-family:system-ui;margin-top:24px;font-size:14px}
</style></head><body><div class="c"><div class="eye"></div><div class="t">ELİŞA yükleniyor...</div></div>
<script>
setTimeout(function(){window.location.href='http://localhost:8765/fullscreen.html'},800);
</script></body></html>
"""

# Kayıtlı pencere konumu (varsa)
try:
    import json as _posjson
    _saved_pos = _posjson.load(open("/tmp/elisha_window.json"))
    _POS_X, _POS_Y = int(_saved_pos["x"]), int(_saved_pos["y"])
except Exception:
    _POS_X, _POS_Y = None, None

window = webview.create_window(
    "ELİŞA",
    html=_SPLASH_HTML,
    width=_W, height=_H,
    x=_POS_X, y=_POS_Y,
    frameless=True,
    resizable=False,
    on_top=True,
    hidden=False,           # Dock'tan açılınca hemen görünsün
    transparent=False,
    easy_drag=False,
    background_color="#050510",  # Siyah arka plan (beyaz sayfa yok)
    js_api=ElishaApi(),
)

# ── Göster / Gizle ────────────────────────────────────────────────────────
def do_hide():
    try: window.hide()
    except Exception: pass
    STATE["visible"] = False

def do_show(reason: str = ""):
    # Kullanıcının yerleştirdiği konumu koru — artık (0,0)'a zorlamıyoruz
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
            # Menü bar "Çıkış" → tüm uygulama temiz kapansın
            if _QUIT_FLAG.exists():
                try: _QUIT_FLAG.unlink()
                except Exception: pass
                _graceful_exit()
            if HIDE_FILE.exists():
                try: HIDE_FILE.unlink()
                except Exception: pass
                do_hide()
            # NOT: WAKE_FILE burada TÜKETİLMEZ — /api/wake_check tek sahibi.
            # Çift tüketici yarışı panelin gizli kalıp görünmez dinlemesine yol açıyordu.
            # 60sn hareketsizlikte otomatik gizle
            if STATE["visible"] and (time.time() - STATE["last"]) > 60:
                do_hide()
        except Exception as e:
            print(f"poll: {e}")
        time.sleep(0.4)

threading.Thread(target=poll, daemon=True).start()

print("✨ ELİŞA gizli modda — menü çubuğundaki ikona bas veya 'hey elişa uyan' de")

# ── Dock gizle KALDIRILDI — artık Dock'ta görünür, güzel ikonla ────────────
def _post_start():
    time.sleep(0.5)
    # macOS Kamera izni — GUI hazır olunca iste (diyalog pencerenin üstünde çıkar)
    if sys.platform == "darwin":
        try:
            import AppKit
            import AVFoundation as AV
            st = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
            if st != 3:
                # Uygulamayı ön plana al — arka plan sürecinde TCC diyaloğu bastırılıyor
                try:
                    AppKit.NSApp.activateIgnoringOtherApps_(True)
                    if window:
                        try:
                            window.evaluate_js("window.focus && window.focus()")
                        except Exception:
                            pass
                except Exception:
                    pass
                time.sleep(0.8)
                AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AV.AVMediaTypeVideo,
                    lambda g: print(f"[TCC] kamera yanıtı: {g}") or _retry_cam_if_denied(g))
                print("[TCC] kamera izni istendi — diyaloğa 'İzin Ver' de")
        except Exception as e:
            print(f"[TCC] kamera: {e}")
    # Dock ikonu ayarla (NSApp artık mevcut)
    if sys.platform == "darwin":
        try:
            import AppKit
            # Dock'ta ELİŞA ikonu göster (Python/roket ikonu yerine)
            icon_path = str(ROOT / "app" / "elisha_icon.icns")
            if Path(icon_path).exists():
                icon = AppKit.NSImage.alloc().initWithContentsOfFile_(icon_path)
                if icon and AppKit.NSApp:
                    AppKit.NSApp.setApplicationIconImage_(icon)
                    print("✅ Dock ikonu ayarlandı")
        except Exception as e:
            print(f"Dock ikon: {e}")

webview.start(func=_post_start, debug=False)
