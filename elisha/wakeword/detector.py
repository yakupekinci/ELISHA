import numpy as np

class WakeWordDetector:
    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("wakeword", {}).get("enabled", True)
        self.threshold = config.get("wakeword", {}).get("threshold", 0.5)
        self.wake_words = [w.lower() for w in config.get("assistant", {}).get("wake_words", ["elişa"])]
        self._engine = None
        self._init_engine()

    def _init_engine(self):
        if not self.enabled:
            print("ℹ️ WakeWord: kapalı (butonla tetiklenecek)")
            return
        # 1) openwakeword dene (hey_jarvis)
        try:
            from openwakeword.model import Model
            self._engine = Model(wakeword_models=["hey_jarvis"])
            print("✅ WakeWord: openWakeWord (hey_jarvis) hazır - 'hey elişa' benzer tetikler")
            self._mode = "openwakeword"
            return
        except Exception as e:
            print(f"ℹ️ openWakeWord yok: {e} -> STT tabanlı 'hey elisha' kullanılacak")
        # 2) STT tabanlı fallback - lazy load (uygulama açılışını hızlandırmak için)
        self._stt_wake = None
        self._engine = "stt_lazy"
        self._mode = "stt"
        print("✅ WakeWord: STT tabanlı 'hey elisha' hazır (lazy, ilk 'Hey ELİŞA' tıklamasında yüklenecek)")
        return

    def detect(self, audio: np.ndarray, sample_rate=16000) -> bool:
        """
        audio: int16 mono 16kHz
        returns True if wake word detected
        """
        if not self.enabled or self._engine is None:
            return False
        try:
            # openwakeword expects 16k, 1280 samples chunks (80ms)
            # Basit: tüm audio'yu chunk'lara böl
            if audio.dtype == np.int16:
                audio_f = audio.astype(np.float32) / 32768.0
            else:
                audio_f = audio
            # need 16k
            chunk_size = 1280
            for i in range(0, len(audio_f) - chunk_size + 1, chunk_size):
                chunk = audio_f[i:i+chunk_size]
                pred = self._engine.predict(chunk)
                # pred dict: {"hey_jarvis": score}
                for score in pred.values():
                    if score > self.threshold:
                        print(f"👂 Wake word tetiklendi! score={score:.2f}")
                        return True
            return False
        except Exception as e:
            print(f"WakeWord detect hatası: {e}")
            return False

    def check_text_trigger(self, text: str) -> bool:
        """Sadece 'hey elişa uyan' ile uyansın - Siri gibi. Diğerleri tetiklemez."""
        t = text.lower().strip()
        # Ana tetik: hey elişa uyan (tüm varyantlar)
        wake_variants = [
            "hey elişa uyan", "hey elisha uyan", "hey elisa uyan",
            "elişa uyan", "elisha uyan", "elisa uyan",
            # kısaltma ama sadece uyan kelimesi varsa
        ]
        if any(w in t for w in wake_variants):
            return True
        # uyansız versiyon sadece "uyan" yoksa da kabul et ama daha katı (tam hey + isim)
        # Kullanıcı "hey elişa" derse de uyansın (kolaylık)
        has_hey = "hey" in t
        has_name = any(n in t for n in ["elişa", "elisha", "elisa", "lisa", "isa", "isha"])
        has_wake = "uyan" in t or "oyan" in t or "uyan," in t
        if has_hey and has_name and has_wake:
            return True
        if has_hey and has_name and len(t.split()) <= 3:  # "hey elişa" kısa ve nets
            # kısa "hey elişa" da kabul, ama "hey elişa saat kaç" gibi komut değil sadece uyandırma
            # komut içinde hey varsa orayı check_text_trigger değil, orchestrator strip edecek
            # burada sadece uyandırma için: 2 kelime ise uyandır
            if t.strip() in ["hey elişa", "hey elisha", "hey elisa", "elişa", "elisha"]:
                return True
        return False

    def strip_wake_word(self, text: str) -> str:
        t = text
        # en uzundan kısaya sırala ki "hey elisha" önce silinsin
        import re
        all_w = sorted(set(self.wake_words + ["hey elisha", "hey elişa", "hey elisa", "elisha", "elisa", "hey lisa"]), key=len, reverse=True)
        for w in all_w:
            t = re.sub(re.escape(w), "", t, flags=re.I)
        return t.strip(" ,.!?")

    def detect_stt(self, audio, sample_rate=16000) -> tuple[bool, str]:
        """STT ile wake word var mı? audio int16 mono 16k -> (bool, transcript)"""
        if getattr(self, "_mode", None) not in ["stt", "stt_lazy"]:
            return False, ""
        # lazy load
        if getattr(self, "_stt_wake", None) is None:
            try:
                from faster_whisper import WhisperModel
                print("⏳ Wake STT modeli yükleniyor (small, bir kez)...")
                self._stt_wake = WhisperModel("small", device="cpu", compute_type="int8")
                self._engine = "stt"
                print("✅ Wake STT hazır")
            except Exception as e:
                print(f"STT wake yükleme hatası: {e}")
                return False, ""
        try:
            import numpy as np
            if audio.dtype == np.int16:
                audio_f = audio.astype(np.float32) / 32768.0
            else:
                audio_f = audio
            for lang in ["tr", "en", None]:
                try:
                    segments, info = self._stt_wake.transcribe(
                        audio_f,
                        language=lang,
                        vad_filter=False,
                        beam_size=3,
                        no_speech_threshold=0.3,
                        temperature=0.0,
                    )
                    text = " ".join([s.text for s in segments]).strip().lower()
                    if not text:
                        continue
                    triggered = self.check_text_trigger(text)
                    if triggered:
                        print(f"👂 Hey ELİŞA algılandı (STT {lang}): '{text}'")
                        return True, text
                except Exception:
                    continue
            return False, text if 'text' in locals() else ""
        except Exception as e:
            print(f"STT wake hatası: {e}")
            return False, ""
