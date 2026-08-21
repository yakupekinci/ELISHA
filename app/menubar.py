"""Menü bar ✦ ikonu — ayrı süreç (rumps ana thread ister)
Tık: 'Uyan' -> /tmp/elisha_wake yazar -> panel açılır
"""
import rumps, pathlib
WAKE = pathlib.Path("/tmp/elisha_wake")
ENABLE = pathlib.Path("/tmp/elisha_wake_enabled")

class Bar(rumps.App):
    def __init__(self):
        super().__init__("✦", quit_button=None)
        self.menu = [
            rumps.MenuItem("✨ ELİŞA Uyan", callback=self.wake),
            rumps.MenuItem(" Gizle", callback=self.hide),
            None,
            rumps.MenuItem("Çıkış", callback=self.quit_all),
        ]
    def wake(self, _):
        ENABLE.write_text("1")
        WAKE.write_text("menü çubuğu")
    def hide(self, _):
        # panele gizle komutu
        pathlib.Path("/tmp/elisha_hide").write_text("1")
    def quit_all(self, _):
        try: ENABLE.unlink()
        except: pass
        rumps.quit_application(None)

if __name__ == "__main__":
    Bar().run()
