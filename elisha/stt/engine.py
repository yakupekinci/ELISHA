import tempfile
from pathlib import Path
import numpy as np

# ─── Whisper'a bağlam veren prompt ────────────────────────────────────────
# Bu prompt modelin doğruluğunu dramatik şekilde artırır:
# - Türkçe özel karakterler (ş, ç, ğ, ı, ö, ü) doğru yazılır
# - Sık kullanılan komutlar tanınır
# - İngilizce teknik terimler (Chrome, Spotify, vb.) doğru algılanır
INITIAL_PROMPT_TR = (
    "Türkçe konuşma. ELİŞA sesli asistan. "
    "Komutlar: saat kaç, hava durumu, dosya aç, müzik çal, chrome aç, "
    "spotify aç, ekran görüntüsü al, ses aç, sesi kıs, sessize al, "
    "neredeyim, konumum ne, internette ara, youtube aç, dosya oluştur, "
    "not al, hatırla, unut, kapat, klasör göster, indirilenler, masaüstü. "
    "Selamlar: merhaba, nasılsın, günaydın, iyi geceler, teşekkürler. "
    "İngilizce: open, close, play, search, volume, screenshot, Chrome, "
    "Safari, Firefox, VS Code, Spotify, YouTube, GitHub, Terminal, Finder. "
    "Şehirler: İstanbul, Ankara, İzmir, Muğla, Antalya, Bursa. "
    "Türkçe özel: şarkı, müzik, çalıştır, güncelle, indir, yükle."
)

# ─── Whisper post-processing: bilinen hatalar ────────────────────────────
# Whisper Türkçe'de bazı kelimeleri sürekli yanlış yazar
_TR_CORRECTIONS = {
    # Yaygın Whisper hataları
    "elisa": "elişa",
    "elişa'ya": "elişa",
    "eleşa": "elişa",
    "alisha": "elişa",
    "hey lisa": "hey elişa",
    "hey lesha": "hey elişa",
    # Komut hataları
    "krom": "chrome",
    "krom'u": "chrome",
    "safary": "safari",
    "fayerfoks": "firefox",
    "spotifay": "spotify",
    "yutup": "youtube",
    "yutube": "youtube",
    "gitap": "github",
    "githab": "github",
    # Türkçe özel karakter hataları
    "calistir": "çalıştır",
    "olustur": "oluştur",
    "guncelle": "güncelle",
    "indirilenlerı": "indirilenleri",
    "masaustu": "masaüstü",
    "dosyayı": "dosyayı",
}


def _post_process_turkish(text: str) -> str:
    """Whisper çıktısını Türkçe için düzelt."""
    if not text:
        return text
    result = text.strip()
    # Kelime bazlı düzeltme
    lower = result.lower()
    for wrong, correct in _TR_CORRECTIONS.items():
        if wrong in lower:
            # case-insensitive replace
            import re
            result = re.sub(re.escape(wrong), correct, result, flags=re.IGNORECASE)
    # Tekrarlayan kelimeler temizle (Whisper bazen "saat saat saat" üretir)
    import re
    result = re.sub(r'\b(\w+)( \1){2,}\b', r'\1', result)
    # Baş/sondaki gereksiz noktalama
    result = result.strip(' .,;:!?')
    return result


def _normalize_audio(audio: np.ndarray) -> np.ndarray:
    """Audio seviyesini normalize et — çok sessiz/yüksek kayıtları düzelt."""
    if len(audio) == 0:
        return audio
    if audio.dtype == np.int16:
        audio_f = audio.astype(np.float32) / 32768.0
    else:
        audio_f = audio.copy()

    # Peak normalize: en yüksek noktayı 0.9'a getir
    peak = np.abs(audio_f).max()
    if peak > 0.01:  # sessizlik değilse
        target_peak = 0.9
        audio_f = audio_f * (target_peak / peak)
        # Clip (aşırı amplification olmasın)
        audio_f = np.clip(audio_f, -1.0, 1.0)

    return audio_f


class STTEngine:
    def __init__(self, config: dict):
        self.config = config
        self.provider = (config.get("stt", {}).get("provider") or "auto").lower()
        self.model_name = config.get("stt", {}).get("model", "medium")
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
            return ""

        try:
            if self.provider == "faster-whisper":
                # Audio normalize — sessiz/yüksek kayıtları düzelt
                audio_f = _normalize_audio(audio)

                segments, info = self._engine.transcribe(
                    audio_f,
                    language=self.language,
                    vad_filter=False,           # dışarıda zaten VAD var
                    beam_size=5,
                    best_of=3,
                    patience=1.5,               # beam search'te daha sabırlı
                    temperature=0.0,            # deterministik (ilk denemede)
                    initial_prompt=INITIAL_PROMPT_TR,
                    no_speech_threshold=0.4,    # 0.3→0.4: sessizliği daha iyi ayıkla
                    log_prob_threshold=-0.8,    # düşük kaliteli segment'leri filtrele
                    condition_on_previous_text=False,
                    compression_ratio_threshold=2.4,  # tekrarlayan çıktıları engelle
                )
                text = " ".join([s.text for s in segments]).strip()

                # Post-processing: bilinen hataları düzelt
                text = _post_process_turkish(text)
                return text

            elif self.provider == "whisper":
                import tempfile, soundfile as sf
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tf:
                    sf.write(tf.name, audio, sample_rate)
                    result = self._engine.transcribe(
                        tf.name,
                        language=self.language,
                        fp16=False,
                        initial_prompt=INITIAL_PROMPT_TR,
                    )
                    text = result.get("text", "").strip()
                    return _post_process_turkish(text)
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
                segments, info = self._engine.transcribe(
                    path, language=self.language, vad_filter=True,
                    initial_prompt=INITIAL_PROMPT_TR,
                )
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
