"""
ELİŞA Menü Bar — ayrı süreç (rumps ana thread ister)
Menü bar simgesine tıklayınca panel açılır / gizlenir.
"""
from __future__ import annotations
import sys, os, atexit, pathlib

if sys.platform == "darwin":
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        if info:
            info["LSUIElement"] = "1"
    except Exception:
        pass

import rumps

WAKE  = pathlib.Path("/tmp/elisha_wake")
HIDE  = pathlib.Path("/tmp/elisha_hide")
ENABLE = pathlib.Path("/tmp/elisha_wake_enabled")
LOCK  = pathlib.Path("/tmp/elisha_menubar.pid")
ROOT  = pathlib.Path(__file__).parent.parent

# ── Tek instance kilidi ────────────────────────────────────────────────────
def acquire_lock() -> bool:
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)
            print(f"⚠️  Menubar zaten çalışıyor (PID {pid}). Çıkılıyor.")
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    LOCK.write_text(str(os.getpid()))
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    return True

# ── Menü bar uygulaması ───────────────────────────────────────────────────
class ELISHABar(rumps.App):
    def __init__(self, icon_path=None):
        kwargs = {"name": "ELİŞA", "quit_button": None}
        if icon_path and pathlib.Path(icon_path).exists():
            kwargs["icon"] = icon_path
            kwargs["template"] = True  # macOS açık/koyu temaya otomatik uyum
        else:
            kwargs["name"] = "✦"

        super().__init__(**kwargs)

        self.menu = [
            rumps.MenuItem("✨  ELİŞA'yı Uyan",    callback=self.wake),
            rumps.MenuItem("◻   Paneli Gizle",      callback=self.hide_panel),
            None,  # Ayırıcı
            rumps.MenuItem("🔊  TTS Açık / Kapalı", callback=self.toggle_tts),
            rumps.MenuItem("🎙  Wakeword Açık / Kapalı", callback=self.toggle_wake),
            None,
            rumps.MenuItem("📊  Durum Kontrol",     callback=self.show_status),
            None,
            rumps.MenuItem("✕   Çıkış",             callback=self.quit_all),
        ]

        self._tts_on  = True
        self._wake_on = True

    # ── Eylemler ─────────────────────────────────────────────────────────
    def wake(self, _):
        ENABLE.write_text("1")
        WAKE.write_text("menü çubuğu")

    def hide_panel(self, _):
        HIDE.write_text("1")

    def toggle_tts(self, sender):
        self._tts_on = not self._tts_on
        label = "🔊  TTS Açık / Kapalı" if self._tts_on else "🔇  TTS Kapalı (tıkla: aç)"
        sender.title = label
        try:
            import urllib.request, json
            url = "http://localhost:8765/api/settings/tts"
            req = urllib.request.Request(
                url, data=json.dumps({"enabled": self._tts_on}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass  # API henüz hazır değilse sessizce geç

    def toggle_wake(self, sender):
        self._wake_on = not self._wake_on
        if self._wake_on:
            ENABLE.write_text("1")
            sender.title = "🎙  Wakeword Açık / Kapalı"
        else:
            try: ENABLE.unlink()
            except Exception: pass
            sender.title = "🔕  Wakeword Kapalı (tıkla: aç)"

    def show_status(self, _):
        try:
            import urllib.request, json
            r = urllib.request.urlopen("http://localhost:8765/api/status", timeout=2)
            j = json.loads(r.read())
            msg = (
                f"ELİŞA Durum\n\n"
                f"STT: {j.get('stt','?')}\n"
                f"TTS: {j.get('tts','?')}\n"
                f"LLM: {j.get('llm','?')}\n"
                f"Wake: {j.get('wake','?')}"
            )
        except Exception:
            msg = "Sunucuya bağlanılamadı.\nELİŞA.command ile başlatın."
        rumps.alert(title="ELİŞA Durum", message=msg, ok="Tamam")

    def quit_all(self, _):
        try: ENABLE.unlink()
        except Exception: pass
        rumps.quit_application(None)

# ── Menü bar PNG ikonunu bul / oluştur ────────────────────────────────────
def _get_icon():
    """Menü bar için küçük template icon."""
    # Önce özel menubar ikonu dene (44x44, template uyumlu)
    menubar_icon = pathlib.Path(__file__).parent / "menubar_icon.png"
    if menubar_icon.exists():
        return str(menubar_icon)

    # Fallback: ana ikon
    png = pathlib.Path(__file__).parent / "elisha_icon.png"
    if png.exists() and png.stat().st_size > 500:
        return str(png)

    # SVG → PNG dönüşümü (cairosvg veya Pillow varsa)
    svg = ROOT / "assets" / "elisha_logo.svg"
    if svg.exists():
        try:
            import cairosvg
            out = str(ROOT / "data" / "elisha_menubar.png")
            cairosvg.svg2png(url=str(svg), write_to=out,
                             output_width=44, output_height=44)
            return out
        except ImportError:
            pass

        try:
            from PIL import Image, ImageDraw
            import io, re

            size = 44
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Arka plan dairesi
            draw.ellipse([1, 1, size-2, size-2],
                         fill=(5, 6, 12, 230),
                         outline=(0, 212, 255, 160), width=1)

            # Sol X — cyan
            s = size / 64
            cyan  = (0, 212, 255, 255)
            pink  = (236, 72, 153, 255)
            white = (230, 252, 255, 200)
            for (x1,y1,x2,y2), col in [
                ((11,19,26,45), cyan), ((26,19,11,45), cyan),
                ((38,19,53,45), pink), ((53,19,38,45), pink),
            ]:
                draw.line([(int(x1*s),int(y1*s)),(int(x2*s),int(y2*s))],
                          fill=col, width=max(2,int(3*s)))

            out = str(ROOT / "data" / "elisha_menubar.png")
            img.save(out)
            return out
        except ImportError:
            pass

    return str(png) if png.exists() else None

# ── Giriş noktası ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not acquire_lock():
        sys.exit(0)

    icon = _get_icon()
    ELISHABar(icon_path=icon).run()
