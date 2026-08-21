import subprocess
import tempfile
import platform
from pathlib import Path

class TTSEngine:
    def __init__(self, config: dict):
        self.config = config
        self.provider = (config.get("tts", {}).get("provider") or "auto").lower()
        self.voice = config.get("tts", {}).get("voice", "tr_TR-dfki-medium")
        self.speed = config.get("tts", {}).get("speed", 1.0)
        self.model_path = config.get("tts", {}).get("piper_model_path", "./voices/tr_TR-dfki-medium.onnx")
        self._engine = None
        self._init_engine()

    def _init_engine(self):
        providers = []
        if self.provider == "auto":
            providers = ["piper", "pyttsx3", "mock"]
        else:
            providers = [self.provider, "mock"]

        for p in providers:
            try:
                if p == "piper":
                    # piper binary kontrolü
                    # pip paketi piper-tts varsa python API deneyelim
                    try:
                        from piper import PiperVoice  # type: ignore
                        model = Path(self.model_path)
                        if model.exists():
                            self._engine = PiperVoice.load(str(model))
                            self.provider = "piper"
                            print(f"✅ TTS: Piper ({self.voice}) hazır")
                            return
                        else:
                            # model yoksa pyttsx3'e düş
                            raise FileNotFoundError(f"Piper model yok: {model}")
                    except ImportError:
                        # piper-tts CLI var mı?
                        import shutil
                        if shutil.which("piper"):
                            # CLI ile çalışacak
                            self._engine = "piper_cli"
                            # model var mı kontrol
                            if Path(self.model_path).exists():
                                self.provider = "piper"
                                print(f"✅ TTS: Piper CLI ({self.voice}) hazır")
                                return
                            else:
                                raise FileNotFoundError("Piper model dosyası yok")
                        else:
                            raise
                elif p == "pyttsx3":
                    import pyttsx3
                    eng = pyttsx3.init()
                    # Türkçe ses seçmeye çalış
                    try:
                        voices = eng.getProperty("voices")
                        # macOS'ta Turkish voice varsa seç
                        tr_voice = None
                        for v in voices:
                            if "tr" in v.id.lower() or "turkish" in v.name.lower() or "yeld" in v.name.lower():
                                tr_voice = v.id
                                break
                        if tr_voice:
                            eng.setProperty("voice", tr_voice)
                        # hız
                        eng.setProperty("rate", int(180 * self.speed))
                    except Exception:
                        pass
                    self._engine = eng
                    self.provider = "pyttsx3"
                    print("✅ TTS: pyttsx3 (sistem sesi) hazır")
                    return
                elif p == "mock":
                    self._engine = "mock"
                    self.provider = "mock"
                    print("⚠️ TTS: mock mod (sadece yazdıracak)")
                    return
            except Exception as e:
                print(f"TTS provider {p} başlatılamadı: {e}")
                continue
        self.provider = "mock"
        self._engine = "mock"

    def speak(self, text: str):
        if not text:
            return
        print(f"🔊 ELİŞA: {text}")
        try:
            if self.provider == "piper":
                if isinstance(self._engine, str) and self._engine == "piper_cli":
                    self._speak_piper_cli(text)
                else:
                    self._speak_piper_python(text)
            elif self.provider == "pyttsx3":
                self._engine.say(text)
                self._engine.runAndWait()
            else:
                # mock: sadece yazdır
                pass
        except Exception as e:
            print(f"TTS hatası: {e}")

    def _speak_piper_python(self, text: str):
        # Piper Python API ile doğrudan sentezle ve çal
        import numpy as np
        try:
            # _engine PiperVoice nesnesi
            voice = self._engine
            # Sentezle
            chunks = list(voice.synthesize(text))
            if not chunks:
                raise RuntimeError("Piper sentez boş döndü")
            # Birleştir
            audio = np.concatenate([np.array(c.audio_float_array) for c in chunks])
            sr = chunks[0].sample_rate
            # sounddevice ile çal
            try:
                import sounddevice as sd
                sd.play(audio, sr)
                sd.wait()
                return
            except Exception:
                # fallback wav yaz + afplay
                import tempfile, soundfile as sf
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    wav_path = tf.name
                sf.write(wav_path, audio, sr)
                self._play_wav(wav_path)
                try:
                    Path(wav_path).unlink()
                except Exception:
                    pass
                return
        except Exception as e:
            print(f"Piper python hatası: {e}, CLI deneniyor")
            self._speak_piper_cli(text)

    def _speak_piper_cli(self, text: str):
        import tempfile, subprocess, platform, pathlib
        model = Path(self.model_path)
        if not model.exists():
            # alternatif ara
            voices_dir = Path("./voices")
            if voices_dir.exists():
                cand = list(voices_dir.glob("*.onnx"))
                if cand:
                    model = cand[0]
                else:
                    raise FileNotFoundError("Hiç Piper modeli bulunamadı")
            else:
                raise FileNotFoundError(f"Model yok: {model}")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav_path = tf.name

        # piper --model ... --output_file wav
        cmd = ["piper", "--model", str(model), "--output_file", wav_path]
        # piper stdin'den text alır
        proc = subprocess.run(cmd, input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            print(f"piper hatası: {proc.stderr.decode()}")
            raise RuntimeError("piper failed")
        # çal
        self._play_wav(wav_path)
        try:
            Path(wav_path).unlink()
        except Exception:
            pass

    def _play_wav(self, wav_path: str):
        try:
            import soundfile as sf
            import sounddevice as sd
            data, sr = sf.read(wav_path)
            sd.play(data, sr)
            sd.wait()
        except Exception:
            # fallback system player
            system = platform.system()
            try:
                if system == "Darwin":
                    subprocess.run(["afplay", wav_path], check=False)
                elif system == "Linux":
                    subprocess.run(["aplay", wav_path], check=False)
                elif system == "Windows":
                    import os
                    os.startfile(wav_path)
            except Exception as e:
                print(f"WAV çalma hatası: {e}")

    @staticmethod
    def download_voice(voice="tr_TR-dfki-medium"):
        """
        Piper Türkçe ses indir (manuel talimat)
        Voiceler: https://huggingface.co/rhasspy/piper-voices
        """
        import os
        voices_dir = Path("./voices")
        voices_dir.mkdir(exist_ok=True)
        print(f"Piper ses indirme talimatı ({voice}):")
        print(f"1) https://huggingface.co/rhasspy/piper-voices/tree/main/tr/tr_TR/dfki/medium")
        print(f"2) {voice}.onnx ve {voice}.onnx.json dosyalarını indir")
        print(f"3) ./voices/ klasörüne koy")
        print(f"Örnek komutlar:")
        print(f"  mkdir -p voices && cd voices")
        print(f"  curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/{voice}.onnx")
        print(f"  curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/{voice}.onnx.json")
        print(f"Alternatif Türkçe ses: tr_TR-fahrettin-medium")
