"""
ELİŞA Android App - Kivy
Telefon için %100 local APK
- STT: telefon mikrofonu -> (future) sherpa-onnx / whisper
- LLM: Ollama ev sunucusuna bağlan veya mock
- TTS: Android system TTS (ücretsiz) + Piper (V2)
"""
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.core.window import Window
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from elisha.orchestrator import ElishaOrchestrator
    HAS_CORE = True
except Exception as e:
    print(f"Core import hatası: {e}")
    HAS_CORE = False

# Android TTS
try:
    from jnius import autoclass
    HAS_JNIUS = True
except Exception:
    HAS_JNIUS = False

class ChatMessage(Label):
    pass

class ElishaAndroidApp(App):
    def build(self):
        Window.clearcolor = (0.1, 0.1, 0.18, 1)
        self.title = "ELİŞA"

        root = BoxLayout(orientation="vertical", padding=10, spacing=10)

        # Header
        header = Label(text="[b]ELİŞA[/b] — Eliyşşa", markup=True, size_hint_y=None, height=50, font_size="22sp", color=(1,1,1,1))
        root.add_widget(header)
        sub = Label(text="%100 Local • Türkçe • Ücretsiz", size_hint_y=None, height=20, font_size="11sp", color=(0.6,0.6,0.8,1))
        root.add_widget(sub)

        # Chat scroll
        self.chat_layout = BoxLayout(orientation="vertical", size_hint_y=None, spacing=8)
        self.chat_layout.bind(minimum_height=self.chat_layout.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.chat_layout)
        root.add_widget(scroll)

        # Input row
        input_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=50, spacing=8)
        self.input = TextInput(hint_text="Mesaj yaz...", multiline=False, size_hint_x=0.7)
        self.input.bind(on_text_validate=lambda x: self.send())
        input_row.add_widget(self.input)
        send_btn = Button(text="Gönder", size_hint_x=0.3, background_color=(0.9,0.27,0.37,1))
        send_btn.bind(on_press=lambda x: self.send())
        input_row.add_widget(send_btn)
        root.add_widget(input_row)

        # Mic row
        mic_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=50, spacing=8)
        self.mic_btn = Button(text="🎙️ Basılı Tut & Konuş", background_color=(0.2,0.6,0.8,1))
        # Kivy'de basılı tut için on_press/on_release
        self.mic_btn.bind(on_press=self.start_listen, on_release=self.stop_listen)
        mic_row.add_widget(self.mic_btn)
        root.add_widget(mic_row)

        # Status
        self.status = Label(text="Hazırlanıyor...", size_hint_y=None, height=24, font_size="11sp", color=(0.7,0.7,0.7,1))
        root.add_widget(self.status)

        # init bot
        Clock.schedule_once(lambda dt: self.init_bot(), 0.5)
        return root

    def init_bot(self):
        self.add_msg("ELİŞA", "Merhaba! Ben ELİŞA. Sana nasıl yardımcı olabilirim?", is_user=False)
        if HAS_CORE:
            try:
                self.bot = ElishaOrchestrator()
                self.status.text = f"Hazır — LLM:{self.bot.llm.provider} TTS:{self.bot.tts.provider}"
                self.add_msg("Sistem", f"Motor hazır: {self.status.text}", is_user=False)
            except Exception as e:
                self.status.text = f"Hata: {e}"
                self.bot = None
        else:
            self.bot = None
            self.status.text = "Core yok — mock mod"

    def add_msg(self, who, text, is_user=False):
        color = (0.2,0.6,1,1) if is_user else (1,1,1,1)
        prefix = "👤" if is_user else "🤖"
        lbl = Label(text=f"{prefix} [b]{who}:[/b] {text}", markup=True, text_size=(Window.width - 40, None), size_hint_y=None, halign="left", valign="top", color=color)
        # height hesapla
        lbl.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1] + 10))
        self.chat_layout.add_widget(lbl)
        # scroll en alta
        Clock.schedule_once(lambda dt: self._scroll_bottom(), 0.1)
        # TTS (Android system TTS)
        if not is_user:
            self.speak_android(text)

    def _scroll_bottom(self):
        # ScrollView'u en alta götürmek için
        pass

    def send(self):
        text = self.input.text.strip()
        if not text:
            return
        self.input.text = ""
        self.add_msg("Sen", text, is_user=True)
        if self.bot:
            resp = self.bot.process_text(text)
        else:
            # mock
            if "chrome" in text.lower() and "aç" in text.lower():
                resp = "Chrome açılıyor. [ACTION: open_app | app=chrome]"
            else:
                resp = f"Anladım: {text} — (mock mod, Ollama yok)"
        self.add_msg("ELİŞA", resp, is_user=False)

    def start_listen(self, *args):
        self.status.text = "🎙️ Dinliyor... (V2'de STT eklenecek)"
        self.mic_btn.text = "🔴 Dinleniyor..."

    def stop_listen(self, *args):
        self.status.text = "Hazır"
        self.mic_btn.text = "🎙️ Basılı Tut & Konuş"
        self.add_msg("Sistem", "Sesli giriş V2'de tam aktif olacak — şimdilik yazarak dene.", is_user=False)

    def speak_android(self, text):
        # Android system TTS via jnius
        if not HAS_JNIUS:
            return
        try:
            # Kısa metinleri konuş
            clean = text.split("[ACTION")[0].strip()[:300]
            if not clean:
                return
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
            Locale = autoclass("java.util.Locale")
            activity = PythonActivity.mActivity
            # Not: gerçek TTS için V2'de service lazım, şimdilik pas
            pass
        except Exception:
            pass

if __name__ == "__main__":
    ElishaAndroidApp().run()
