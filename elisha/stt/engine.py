import tempfile
from pathlib import Path
import numpy as np

class STTEngine:
    def __init__(self, config: dict):
        self.config = config
        self.provider = (config.get("stt", {}).get("provider") or "auto").lower()
        self.model_name = config.get("stt", {}).get("model", "small")
        self.language = config.get("stt", {}).get("language", "tr")
        self._engine = None
        self._init_engine()

    def _init_engine(self):
        # auto: try faster-whisper -> whisper -> mock
        providers = []
        if self.provider == "auto":
            providers = ["faster-whisper", "whisper", "mock"]
        else:
            providers = [self.provider, "mock"]

        for p in providers:
            try:
                if p == "faster-whisper":
                    from faster_whisper import WhisperModel
                    # tiny/base/small/medium
                    # device auto: prefer cpu, use float32 for compatibility
                    self._engine = WhisperModel(self.model_name, device="cpu", compute_type="int8")
                    self.provider = "faster-whisper"
                    print(f"✅ STT: faster-whisper ({self.model_name}) hazır")
                    return
                elif p == "whisper":
                    import whisper
                    self._engine = whisper.load_model(self.model_name)
                    self.provider = "whisper"
                    print(f"✅ STT: openai-whisper ({self.model_name}) hazır")
                    return
                elif p == "mock":
                    self._engine = "mock"
                    self.provider = "mock"
                    print("⚠️ STT: mock mod (model yok, test için klavyeden yazılacak)")
                    return
            except Exception as e:
                print(f"STT provider {p} başlatılamadı: {e}")
                continue

    def transcribe(self, audio: np.ndarray, sample_rate=16000) -> str:
        if audio is None or len(audio) == 0:
            return ""
        if self.provider == "mock":
            # mock: kullanıcıdan input al
            return ""

        try:
            if self.provider == "faster-whisper":
                # faster-whisper expects float32 [-1,1]
                if audio.dtype == np.int16:
                    audio_f = audio.astype(np.float32) / 32768.0
                else:
                    audio_f = audio
                segments, info = self._engine.transcribe(
                    audio_f,
                    language=self.language,
                    vad_filter=False,           # dışarıda zaten VAD var
                    beam_size=5,
                    best_of=5,
                    temperature=0.0,
                    initial_prompt="Türkçe: saat kaç, hava durumu, dosya aç, müzik çal.",
                    no_speech_threshold=0.3,
                    condition_on_previous_text=False,
                )
                text = " ".join([s.text for s in segments]).strip()
                return text
            elif self.provider == "whisper":
                import tempfile, soundfile as sf
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tf:
                    sf.write(tf.name, audio, sample_rate)
                    result = self._engine.transcribe(tf.name, language=self.language, fp16=False)
                    return result.get("text", "").strip()
        except Exception as e:
            print(f"STT hatası: {e}")
            return ""
        return ""

    def transcribe_file(self, wav_path: str) -> str:
        segs, _ = self.transcribe_file_full(wav_path)
        return " ".join(segs).strip()

    def transcribe_file_full(self, path: str):
        """returns (segments_text_list, language) — webm/wav/mp3 hepsi decode edilir"""
        try:
            import soundfile as sf
            data, sr = sf.read(path)
        except Exception:
            # soundfile webm okuyamazsa faster-whisper direkt dosyadan dene
            if self.provider == "faster-whisper":
                segments, info = self._engine.transcribe(path, language=self.language, vad_filter=True)
                return [s.text for s in segments], info.language
            return [], "unknown"
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            from scipy.signal import resample
            num = int(len(data) * 16000 / sr)
            data = resample(data, num)
        if data.dtype != np.int16:
            data = (np.asarray(data) * 32768).astype(np.int16)
        text = self.transcribe(data, 16000)
        return ([text] if text else []), self.language
