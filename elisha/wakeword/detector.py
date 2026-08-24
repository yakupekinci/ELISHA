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
        # 0) ÖZEL MODEL: data/wakeword/*.onnx varsa öncelikli kullan
        #    (openwakeword.com/train ile eğitilen 'hey elişa' modeli buraya konur)
        from pathlib import Path as _P
        _custom_dir = _P("data") / "wakeword"
        _custom_models = sorted(_custom_dir.glob("*.onnx")) if _custom_dir.exists() else []
        if _custom_models:
            try:
                from openwakeword.model import Model
                self._engine = Model(
                    wakeword_models=[str(p) for p in _custom_models],
                    inference_framework="onnx",
                )
                self._custom_names = [p.stem for p in _custom_models]
                print(f"✅ WakeWord: ÖZEL model yüklendi → {[p.name for p in _custom_models]}")
                self._mode = "openwakeword"
                return
            except Exception as e:
                print(f"⚠️ Özel wake word modeli yüklenemedi ({e}) → hazır modellere dönülüyor")
        # 1) openwakeword dene (hey_jarvis) — onnxruntime backend ile
        try:
            from openwakeword.model import Model
            self._engine = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            print("✅ WakeWord: openWakeWord (hey_jarvis + onnx) hazır - 'hey elişa' benzer tetikler")
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
        """'hey elişa', 'elişa uyan' veya kısa cümle içinde isim geçmesiyle uyansın."""
        t = text.lower().strip()
        # Türkçe telaffuz varyantları (whisper 'elişa'yı farklı yazabilir)
        name_hits = ["elişa", "elişam", "elisha", "elisa", "ilişa", "elişo", "eliş",
                     "elisa", "eli za", "e lisha", "lisa"]
        has_name = any(n in t for n in name_hits)
        if not has_name:
            return False
        has_hey = "hey" in t or "ey" in t.split()[:1]
        has_wake = "uyan" in t or "uyandin" in t
        # 1) isim + uyan → kesin uyandır
        if has_wake:
            return True
        # 2) hey + isim → klasik tetik ("hey elişa saat kaç" dahil — komut akar)
        if has_hey:
            return True
        # 3) yalnızca kısa ütterance'ta çıplak isim ("elişa?" gibi) → uyandır
        if len(t.split()) <= 4:
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
                wake_model = self.config.get("stt", {}).get("model", "medium")
                print(f"⏳ Wake STT modeli yükleniyor ({wake_model}, bir kez)...")
                self._stt_wake = WhisperModel(wake_model, device="cpu", compute_type="int8")
                self._engine = "stt"
                print(f"✅ Wake STT hazır ({wake_model})")
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
