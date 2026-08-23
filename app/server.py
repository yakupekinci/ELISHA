"""
ELİŞA Web Server — Threading + cache + local STT
Çalıştır: python3 app/server.py  -> http://localhost:8765
"""
import json, base64, tempfile, threading, time, queue
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.orchestrator import ElishaOrchestrator
from elisha.log import log, err
from elisha import settings

PORT = 8765
WEB_DIR = Path(__file__).parent / "web"

# ---------- Listen jobs (async mic kayıt) ----------
_listen_jobs: dict = {}   # rid -> {status, text, silent, error}
_whisper_model = None
_whisper_lock = threading.Lock()

def _get_whisper():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            from faster_whisper import WhisperModel
            from elisha.config import load_config
            import warnings
            cfg = load_config()
            stt_model = cfg.get("stt", {}).get("model", "medium")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _whisper_model = WhisperModel(stt_model, device="cpu", compute_type="int8")
            log("STT", f"faster-whisper ({stt_model}) yüklendi")
    return _whisper_model

# ── Uyarı sesleri (afplay ile anlık) ──────────────────────────
_CHIME_WAKE_PATH = None
_CHIME_RESP_PATH = None
_CHIME_LOCK = threading.Lock()

def _build_chime(freqs, durations, sr=22050, vol=0.28):
    """Kısa bir bip sesi üret; freqs/durations listesi = ardışık tonlar."""
    import numpy as np
    chunks = []
    for freq, dur in zip(freqs, durations):
        n = int(sr * dur)
        t = np.linspace(0, dur, n)
        tone = np.sin(2 * np.pi * freq * t).astype(np.float32) * vol
        # yumuşak başlangıç/bitiş zarfı
        fade = min(int(0.015 * sr), n // 4)
        tone[:fade]  *= np.linspace(0, 1, fade)
        tone[-fade:] *= np.linspace(1, 0, fade)
        chunks.append(tone)
    return np.concatenate(chunks)

def _get_chime(kind: str) -> str:
    """Chime WAV dosyasını oluştur/cache'le."""
    global _CHIME_WAKE_PATH, _CHIME_RESP_PATH
    import numpy as np, soundfile as sf, tempfile
    with _CHIME_LOCK:
        path_attr = "_CHIME_WAKE_PATH" if kind == "wake" else "_CHIME_RESP_PATH"
        cached = _CHIME_WAKE_PATH if kind == "wake" else _CHIME_RESP_PATH
        if cached and Path(cached).exists():
            return cached
        sr = 22050
        if kind == "wake":
            # İki kısa yükselen ton: "dinliyorum" hissi
            audio = _build_chime([660, 880], [0.08, 0.10], sr=sr, vol=0.22)
        else:
            # Tek yumuşak alçalan ton: "cevap veriyorum" hissi
            audio = _build_chime([550, 440], [0.07, 0.09], sr=sr, vol=0.18)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            sf.write(tf.name, audio, sr)
            p = tf.name
        if kind == "wake":
            _CHIME_WAKE_PATH = p
        else:
            _CHIME_RESP_PATH = p
    return p

def _play_chime(kind: str = "wake"):
    """Chime'ı arka planda çal — bloklama yok."""
    try:
        import subprocess as _sp
        p = _get_chime(kind)
        _sp.Popen(["afplay", "-v", "0.55", p],
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    except Exception as e:
        log("CHIME", f"çalınamadı: {e}")

# ── STT hallucination blacklist ──────────────────────────────
# Whisper gürültüyü video altyazısı gibi yanlış tanır — bu listedekiler filtrelenir.
# NOT: Türkçe gerçek kelimeler buraya EKLENMEMELİ — yanlış silinir.
_STT_HALLUCINATIONS = {
    # İngilizce hallucination
    "subtitle", "sub", "thanks", "thank you", "bye", "goodbye",
    "like", "subscribe", "follow", "share", "comment",
    "you", "the", "and", "is", "it", "this",
    # Türkçe hallucination (gerçek komut DEĞİL, sadece gürültü çıktısı)
    "abone ol", "beğen", "altyazı", "çeviri", "video", "izleyin",
    "abone olun", "beğenin", "paylaşın", "bildirimi açın",
    "kanala abone", "videoyu beğen",
    # Tekrarlayan saçmalık
    "...", "…", "♪", "♫", "🎵",
}

def _is_hallucination(text: str) -> bool:
    """Whisper'ın arka plan gürültüsünü şarkı/altyazı gibi yanlış tanıması."""
    t = text.lower().strip().rstrip(".")
    if t in _STT_HALLUCINATIONS:
        return True
    # Çok kısa veya sadece noktalama
    if len(t) < 2:
        return True
    # Tamamen İngilizce ve kısa (Türkçe bekliyoruz)
    import re
    if len(t) < 15 and re.match(r'^[a-z\s.,!?\']+$', t) and not re.search(r'[şçğıöüŞÇĞİÖÜ]', text):
        # Sadece ASCII ve Türkçe özel karakter yok = muhtemelen İngilizce hallucination
        # Ama bilinen komutlar ve Türkçe ASCII kelimeler hariç
        _ALLOWED_EN = {"open", "close", "play", "stop", "search", "hey elisha"}
        _TURKISH_ASCII = {"merhaba", "selam", "tamam", "evet", "hayir", "saat", "naber",
                          "hey elisa", "elisa", "nasil", "tesekkur", "sagol"}
        if t in _TURKISH_ASCII or any(w in t for w in _TURKISH_ASCII):
            return False
        if t not in _ALLOWED_EN and not any(w in t for w in _ALLOWED_EN):
            return True
    # Tekrarlayan pattern (aynı kelime 3+ kez)
    words = t.split()
    if len(words) >= 3 and len(set(words)) == 1:
        return True
    return False

def _do_listen(rid: str, duration: float):
    # Wake daemon kayıt+transkripsiyon boyunca tetiklenmesin (çift dinleme çakışması)
    import numpy as np
    try: _MIC_ACTIVE_FLAG.write_text("1")
    except Exception: pass
    try:
        _do_listen_inner(rid, duration)
    finally:
        try: _MIC_ACTIVE_FLAG.unlink(missing_ok=True)
        except Exception: pass

def _do_listen_inner(rid: str, duration: float):
    import numpy as np
    # Anında uyarı sesi: "dinliyorum" hissi
    _play_chime("wake")

    try:
        # VAD tabanlı kayıt: konuşma bitince durur (fixed-duration yerine)
        from elisha.audio import record_until_silence
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            audio = record_until_silence(
                sample_rate=16000,
                vad_aggressiveness=1,      # daha az katı (2→1)
                silence_ms=900,
                max_seconds=int(duration),
            )
    except Exception as e:
        _listen_jobs[rid] = {"status": "done", "error": f"mic: {e}"}
        return

    mean_level = int(np.abs(audio).mean()) if len(audio) > 0 else 0
    log("STT", f"kayıt: {len(audio)/16000:.1f}sn  seviye={mean_level}")

    if len(audio) == 0 or mean_level < 50:
        _listen_jobs[rid] = {"status": "done", "text": "", "silent": True}
        return

    try:
        model = _get_whisper()
        from elisha.stt.engine import INITIAL_PROMPT_TR, _normalize_audio, _post_process_turkish
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Audio normalize (sessiz/yüksek kayıtları düzelt)
            audio_f = _normalize_audio(audio)
            segs, info = model.transcribe(
                audio_f,
                language="tr",
                vad_filter=False,          # kendi VAD'ımız zaten sesi ayıkladı
                beam_size=5,
                best_of=3,
                patience=1.5,
                temperature=0.0,           # deterministik
                initial_prompt=INITIAL_PROMPT_TR,
                no_speech_threshold=0.4,
                log_prob_threshold=-0.8,
                condition_on_previous_text=False,
                compression_ratio_threshold=2.4,
                word_timestamps=False,
            )
        text = " ".join(s.text for s in segs).strip()
        # Post-processing: bilinen Türkçe hatalarını düzelt
        text = _post_process_turkish(text)
        log("STT", f"transkripsiyon: {text!r}  (lang={info.language} conf={info.language_probability:.2f})")
        # Hallucination filtresi
        if _is_hallucination(text):
            log("STT", f"hallucination atlandı: {text!r}")
            _listen_jobs[rid] = {"status": "done", "text": "", "silent": True}
            return
        if len(text) > 300:
            text = text[:300]
        _listen_jobs[rid] = {"status": "done", "text": text}
    except Exception as e:
        _listen_jobs[rid] = {"status": "done", "error": f"stt: {e}"}

# Aktif SSE istemciler (agent durum yayını)
_sse_clients = set()
_sse_lock = threading.Lock()

_bot = None
_bot_lock = threading.Lock()
def get_bot():
    global _bot
    with _bot_lock:
        if _bot is None:
            log("SERVER", "ELİŞA yükleniyor...")
            _bot = ElishaOrchestrator()
            log("SERVER", f"✅ hazır: {_bot.stt.provider} / {_bot.tts.provider} / {_bot.llm.provider}")
    return _bot

# Piper voice cache (her istekte yeniden yükleme!)
_piper_voice = None
_piper_lock = threading.Lock()
def get_piper():
    global _piper_voice
    with _piper_lock:
        if _piper_voice is None:
            from piper import PiperVoice
            # Seçili cinsiyete göre model çözümle (tts.set_gender ile senkron)
            try:
                gender = get_bot().tts.gender
            except Exception:
                gender = "female"
            catalog = {
                "female": "tr_TR-dfki-medium.onnx",
                "male": "tr_TR-fahrettin-medium.onnx",
            }
            model = (Path("./voices") / catalog.get(gender, catalog["female"])).resolve()
            if not model.exists():
                alt = Path("./voices/tr_TR-dfki-medium.onnx").resolve()
                if not alt.exists():
                    raise FileNotFoundError(f"piper model yok: {model}")
                model = alt
            _piper_voice = PiperVoice.load(str(model))
            log("TTS", f"Piper cache'lendi ({model.stem})")
    return _piper_voice

# LLM chat lock — aynı anda tek istek işlensin (Ollama güvenliği)
_chat_lock = threading.Lock()

# TTS lock — aynı anda tek ses çalsın
_tts_lock = threading.Lock()

# Konuşma durumu — barge-in ve UI senkronizasyonu için
_speak_state = {"active": False, "barge": False}

_TTS_MUTE_FLAG = Path("/tmp/elisha_tts_active")
_MIC_ACTIVE_FLAG = Path("/tmp/elisha_mic_active")
_BARGE_FLAG = Path("/tmp/elisha_barge")

def _clean_for_tts(text: str) -> str:
    """LLM cevabını seslendirmeye uygun hale getir: markdown/kod/URL temizle."""
    import re as _re
    t = text.strip()
    t = _re.sub(r'\[ACTION:[^\]]+\]', '', t)
    t = _re.sub(r'```[\s\S]*?```', ' kod örneği hazırladım. ', t)   # kod blokları okunmaz
    t = _re.sub(r'`[^`\n]+`', '', t)                                 # inline kod
    t = _re.sub(r'https?://\S+', '', t)                              # URL'ler harf harf okunur
    t = _re.sub(r'^#{1,6}\s*', '', t, flags=_re.M)                   # başlıklar
    t = _re.sub(r'(\*\*|__|\*|_)', '', t)                            # kalın/italik işaretleri
    t = _re.sub(r'^\s*[-*+]\s+', '', t, flags=_re.M)                 # liste imleri
    t = _re.sub(r'[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]', '', t)  # emoji
    t = _re.sub(r'[ \t]+', ' ', t)
    t = _re.sub(r'\n{2,}', '. ', t).replace('\n', ' ').strip()
    # Cümle sınırında kes (kelime ortasından değil)
    if len(t) > 320:
        cut = t[:320]
        last = max(cut.rfind('.'), cut.rfind('!'), cut.rfind('?'), cut.rfind(':'))
        t = cut[:last + 1] if last > 80 else cut.rsplit(' ', 1)[0] + '...'
    return t.strip()

def _barge_monitor(proc, threshold=None, sustain_blocks=5, grace_s=None):
    """TTS çalarken mikrofonu izle; kullanıcı konuşursa çalmayı kes (barge-in).
    Eşik ve bekleme config.yaml → audio.barge_threshold / barge_grace_s."""
    import numpy as np, time as _t
    try:
        import sounddevice as _sd
    except Exception:
        return
    if threshold is None or grace_s is None:
        try:
            from elisha.config import load_config
            acfg = load_config().get("audio", {})
        except Exception:
            acfg = {}
        threshold = threshold if threshold is not None else float(acfg.get("barge_threshold", 0.035))
        grace_s = grace_s if grace_s is not None else float(acfg.get("barge_grace_s", 0.8))
    block = int(16000 * 0.1)   # 100ms bloklar
    hit = 0
    try:
        _t.sleep(grace_s)      # ilk hece + chime geçsin (kendi sesi tetiklemesin)
        while proc.poll() is None and _speak_state["active"]:
            rec = _sd.rec(block, samplerate=16000, channels=1, dtype='float32')
            _sd.wait()
            rms = float(np.sqrt(np.mean(rec.flatten() ** 2)))
            if rms > threshold:
                hit += 1
                if hit >= sustain_blocks:
                    print(f"[BARGE] 🛑 konuşma algılandı (rms={rms:.3f}) — seslendirme kesildi")
                    _speak_state["barge"] = True
                    try: _BARGE_FLAG.write_text("1")
                    except Exception: pass
                    try: proc.terminate()
                    except Exception: pass
                    return
            else:
                hit = max(0, hit - 1)
    except Exception as e:
        log("BARGE", f"izleyici durdu: {e}")

def _speak_async(text: str):
    """Cevabı seslendir: Piper (en iyi) → pyttsx3 (yedek).
    Sırasında: wake daemon susturulur + kullanıcı sözü keserse barge-in."""
    clean = _clean_for_tts(text)
    if len(clean) < 2:
        return
    # Wake daemon'ı sustur (chime dahil tüm süre)
    try: _TTS_MUTE_FLAG.write_text("1")
    except Exception: pass
    _speak_state["active"] = True
    _speak_state["barge"] = False
    try: _BARGE_FLAG.unlink(missing_ok=True)
    except Exception: pass
    try:
        # Cevap öncesi hafif uyarı sesi
        _play_chime("response")
        played = False
        with _tts_lock:
            # 1. Piper dene
            try:
                import numpy as np, soundfile as sf, tempfile, subprocess as _sp
                voice = get_piper()
                chunks = list(voice.synthesize(clean))
                if chunks:
                    audio = np.concatenate([np.array(c.audio_float_array) for c in chunks])
                    sr = chunks[0].sample_rate
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                        wav_path = tf.name
                        sf.write(wav_path, audio, sr)
                    proc = _sp.Popen(["afplay", wav_path],
                                     stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                    played = True
                    # Barge-in izleyici (kullanıcı üstten konuşursa kes)
                    threading.Thread(target=_barge_monitor, args=(proc,), daemon=True).start()
                    proc.wait()
                    from pathlib import Path as _P
                    try: _P(wav_path).unlink()
                    except Exception: pass
            except Exception:
                pass  # Piper yok, pyttsx3'e düş
            # 2. pyttsx3 yedek
            if not played:
                try:
                    import pyttsx3
                    engine = pyttsx3.init()
                    voices = engine.getProperty('voices')
                    for v in voices:
                        if 'tr' in (v.languages[0] if v.languages else b'').lower() if hasattr(v.languages[0] if v.languages else b'', 'lower') else False:
                            engine.setProperty('voice', v.id); break
                    engine.setProperty('rate', 180)
                    engine.say(clean)
                    engine.runAndWait()
                except Exception as e:
                    log("TTS", f"pyttsx3 hata: {e}")
    finally:
        _speak_state["active"] = False
        # yankı kuyruğu bitmeden wake'i açma
        threading.Timer(0.6, lambda: _TTS_MUTE_FLAG.unlink(missing_ok=True)).start()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB_DIR), **kw)

    def log_message(self, fmt, *args):
        # poll spamini gizle
        try:
            line = fmt % args if args else fmt
        except Exception:
            line = str(args)
        if "/api/wake_check" in line or "/api/health" in line:
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200); self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/status":
                bot = get_bot()
                providers = bot.llm.router.available_providers if hasattr(bot.llm, 'router') else []
                primary = bot.llm.router.primary_provider if hasattr(bot.llm, 'router') else None
                self._json(200, {
                    "name": "ELİŞA",
                    "stt": bot.stt.provider,
                    "tts": bot.tts.provider,
                    "llm": bot.llm.model,
                    "provider": primary.name if primary else bot.llm.provider,
                    "providers": providers,
                    "wake": "hey elişa uyan",
                })
                return
            if parsed.path == "/api/health":
                self._json(200, {"ok": True})
                return
            if parsed.path == "/api/barge":
                # UI konuşma bitişini ve söz kesmeyi buradan öğrenir
                barge = _speak_state["barge"]
                if barge:
                    _speak_state["barge"] = False
                    try: _BARGE_FLAG.unlink(missing_ok=True)
                    except Exception: pass
                self._json(200, {"speaking": _speak_state["active"], "barge": barge})
                return
            if parsed.path == "/api/wake_check":
                p = Path("/tmp/elisha_wake")
                if p.exists():
                    try:
                        txt = p.read_text().strip(); p.unlink()
                        self._json(200, {"wake": True, "text": txt}); return
                    except: pass
                self._json(200, {"wake": False})
                return
            if parsed.path == "/api/settings":
                self._json(200, settings.get_all())
                return
            if parsed.path == "/api/wake_enable":
                Path("/tmp/elisha_wake_enabled").write_text("1")
                self._json(200, {"enabled": True})
                return
            if parsed.path == "/api/wake_disable":
                try: Path("/tmp/elisha_wake_enabled").unlink()
                except: pass
                self._json(200, {"enabled": False})
                return
            if parsed.path == "/api/voices":
                bot = get_bot()
                self._json(200, {
                    "voices": bot.tts.available_voices,
                    "current_gender": bot.tts.gender,
                })
                return
        except Exception as e:
            self._json(500, {"error": str(e)})
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")

        try:
            if parsed.path == "/api/wake":
                # ELISHAToggle.app veya web UI'dan gelen wake isteği
                Path("/tmp/elisha_wake_enabled").write_text("1")
                Path("/tmp/elisha_wake").write_text("api")
                self._json(200, {"ok": True, "wake": True})
                return

            if parsed.path == "/api/settings":
                data = json.loads(body) if body else {}
                if not data or not isinstance(data, dict):
                    return self._json(400, {"error": "expected JSON object with key/value pairs"})
                settings.set_many(data)
                self._json(200, {"ok": True, "settings": settings.get_all()})
                return

            if parsed.path == "/api/voice":
                data = json.loads(body) if body else {}
                gender = data.get("gender", "").lower()
                if gender not in ("female", "male"):
                    return self._json(400, {"error": "gender must be 'female' or 'male'"})
                bot = get_bot()
                ok = bot.tts.set_gender(gender)
                if ok:
                    # Piper cache'i de güncelle
                    global _piper_voice
                    with _piper_lock:
                        _piper_voice = None  # yeniden yüklenecek
                    self._json(200, {"ok": True, "gender": gender})
                else:
                    self._json(404, {"error": f"{gender} sesi yüklü değil. voices/ klasörüne model dosyasını indirin."})
                return

            if parsed.path == "/api/listen":
                # Async kayıt: hemen 202 döner, JS /api/listen/result poll eder
                import uuid as _uuid
                rid = _uuid.uuid4().hex
                data = json.loads(body) if body else {}
                duration = min(float(data.get("duration", 5)), 10)
                _listen_jobs[rid] = {"status": "recording"}
                import threading as _th
                _th.Thread(target=_do_listen, args=(rid, duration), daemon=True).start()
                return self._json(202, {"id": rid})

            if parsed.path == "/api/listen/result":
                data = json.loads(body) if body else {}
                rid = data.get("id", "")
                job = _listen_jobs.get(rid)
                if not job:
                    return self._json(404, {"error": "no such job"})
                return self._json(200, job)

            if parsed.path == "/api/chat":
                data = json.loads(body) if body else {}
                text = (data.get("text") or "").strip()
                tts_on = data.get("tts", True)  # varsayılan: sesli
                if not text:
                    return self._json(400, {"error": "no text"})
                bot = get_bot()
                with _chat_lock:
                    reply = bot.process_text(text)
                # Otomatik TTS — server tarafında afplay ile çal
                if tts_on and reply and len(reply.strip()) > 1:
                    threading.Thread(
                        target=_speak_async, args=(reply,), daemon=True
                    ).start()
                self._json(200, {"reply": reply, "text": text})
                return

            if parsed.path == "/api/chat_stream":
                # SSE: status olayları + kademeli final cevap
                data = json.loads(body) if body else {}
                text = (data.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": "no text"})
                bot = get_bot()
                self._chat_stream_sse(bot, text)
                return

            if parsed.path == "/api/tts":
                data = json.loads(body) if body else {}
                text = (data.get("text") or "").strip()[:500]
                if not text:
                    return self._json(400, {"error": "no text"})
                import numpy as np, soundfile as sf
                voice = get_piper()
                chunks = list(voice.synthesize(text))
                audio = np.concatenate([np.array(c.audio_float_array) for c in chunks])
                sr = chunks[0].sample_rate
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    wav_path = tf.name
                    sf.write(wav_path, audio, sr)
                    wav_bytes = Path(wav_path).read_bytes()
                # Server tarafında da afplay ile çal (pywebview autoplay sorunu bypass)
                import subprocess as _sp
                _sp.Popen(["afplay", wav_path],
                          stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                self._json(200, {"audio": base64.b64encode(wav_bytes).decode(), "sr": sr})
                return

            if parsed.path == "/api/stt":
                # browser MediaRecorder'dan gelen ses (webm/opus) -> local whisper
                if not body:
                    return self._json(400, {"error": "no audio"})
                suffix = ".webm" if "webm" in ctype else ".wav"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    tf.write(body); tmp_path = tf.name
                try:
                    bot = get_bot()
                    segments, info = bot.stt.transcribe_file_full(tmp_path)
                    text = " ".join(segments).strip()
                    self._json(200, {"text": text, "language": info})
                finally:
                    try: Path(tmp_path).unlink()
                    except: pass
                return

            self._json(404, {"error": "not found"})
        except Exception as e:
            import traceback; traceback.print_exc()
            self._json(500, {"error": str(e)})

    def _json(self, code, obj):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass  # İstemci bağlantıyı kesti — sessizce geç

    # ---------- SSE streaming chat ----------

    def _sse_send(self, obj):
        try:
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    def _chat_stream_sse(self, bot, text):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = queue.Queue()

        def on_status(s):
            q.put(("status", s))

        def worker():
            old_cb = getattr(bot, "status_callback", None)
            bot.status_callback = on_status
            try:
                with _chat_lock:  # LLM seri çalışsın
                    reply = bot.process_text(text)
                q.put(("done", reply or ""))
            except Exception as e:
                q.put(("error", str(e)))
            finally:
                bot.status_callback = old_cb

        threading.Thread(target=worker, daemon=True).start()

        while True:
            try:
                kind, val = q.get(timeout=180)
            except queue.Empty:
                self._sse_send({"type": "error", "error": "zaman aşımı"})
                break
            if kind == "status":
                self._sse_send({"type": "status", "text": val})
            elif kind == "error":
                self._sse_send({"type": "error", "error": val})
                break
            else:  # done -> cevabı kademeli gönder + server TTS
                words, buf = val.split(" "), ""
                for w in words:
                    buf += (w + " ")
                    self._sse_send({"type": "token", "text": w + " "})
                    time.sleep(0.012)
                self._sse_send({"type": "done", "reply": val})
                # Server tarafında TTS çal
                threading.Thread(target=_speak_async, args=(val,), daemon=True).start()
                break

def main():
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    # başlangıçta ısıt (arka planda, server hemen açılsın)
    threading.Thread(target=get_bot, daemon=True).start()
    def _warm_piper():
        try: get_piper()
        except Exception as e: err(f"piper warmup: {e}")
    threading.Thread(target=_warm_piper, daemon=True).start()
    httpd = ThreadingHTTPServer(("", PORT), Handler)  # ÇOKLU THREAD - Failed to fetch fix
    httpd.daemon_threads = True
    log("SERVER", f"✨ web http://localhost:{PORT} (threading)")
    try: httpd.serve_forever()
    except KeyboardInterrupt: log("SERVER", "durdu")

if __name__ == "__main__":
    main()
