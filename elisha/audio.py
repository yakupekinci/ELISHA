import collections
import webrtcvad
import numpy as np

try:
    import sounddevice as sd
    import soundfile as sf
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False

def list_input_devices():
    if not HAS_SOUNDDEVICE:
        return []
    return sd.query_devices()

# ── Silero VAD v6 (faster-whisper paketiyle gelir) ────────────────────────
# webrtcvad'dan çok daha isabetli: sessizde ~0.02, konuşmada ~0.7+ olasılık.
_SILERO = {"sess": None, "h": None, "c": None, "failed": False}

def _get_silero():
    """silero_vad_v6.onnx'i lazy yükle (onnxruntime + faster_whisper gerekli).
    Yoksa/çökerse kalıcı olarak vazgeç → webrtcvad'a düşer."""
    if _SILERO["failed"]:
        return None
    if _SILERO["sess"] is None:
        try:
            import onnxruntime as ort
            from pathlib import Path as _P
            import faster_whisper as _fw
            mp = _P(_fw.__file__).parent / "assets" / "silero_vad_v6.onnx"
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1   # mikrofon callback'ini bloklamak yok
            _SILERO["sess"] = ort.InferenceSession(str(mp), sess_options=opts)
            _SILERO["h"] = np.zeros((1, 1, 128), np.float32)
            _SILERO["c"] = np.zeros((1, 1, 128), np.float32)
        except Exception:
            _SILERO["failed"] = True
    return None if _SILERO["failed"] else _SILERO["sess"]

def _silero_reset():
    if _SILERO.get("h") is not None:
        _SILERO["h"][:] = 0
        _SILERO["c"][:] = 0

def _silero_prob(x) -> float:
    """Tek pencere (576 örnek ≈ 36ms) için konuşma olasılığı. Hata → -1.0"""
    sess = _get_silero()
    if sess is None:
        return -1.0
    try:
        out = sess.run(None, {
            "input": x[None, :].astype(np.float32),
            "h": _SILERO["h"], "c": _SILERO["c"],
        })
        _SILERO["h"], _SILERO["c"] = out[1], out[2]
        return float(np.ravel(out[0])[0])
    except Exception:
        return -1.0

def record_until_silence(
    sample_rate=16000,
    vad_aggressiveness=2,
    silence_ms=900,
    max_seconds=8,
    frame_ms=30,
    no_speech_s=2.0,
    calibration_s=0.35,
):
    """
    Mikrofonu dinle, konuşma bitene (sessizlik) kadar kaydet.
    webrtcvad ile sessizlik tespiti.
    no_speech_s: Bu süre içinde hiç konuşma başlamazsa erken çık
                 (sürekli sohbette boşa bekleme olmasın).
    calibration_s: Başlangıçta ortam gürültüsünü ölç → adaptif eşikler.
                   TV/müzik gibi gürültülü odalarda sabit eşik
                   ("her şeyi konuşma sanma") problemini çözer.
    Returns: numpy int16 array (mono, 16kHz)
    """
    if not HAS_SOUNDDEVICE:
        raise RuntimeError("sounddevice kurulu değil")

    # Agresiflik 1 = daha az katı (2-3 çok fazla gürültü filtreler)
    _agg = min(vad_aggressiveness, 1)
    vad = webrtcvad.Vad(_agg)
    frame_samples = int(sample_rate * frame_ms / 1000)
    num_silence_frames = int(silence_ms / frame_ms)  # kaç frame sessizlik = konuşma bitti

    # küçük pre-buffer: konuşma başlangıcını kaçırma (300ms = 10 frame)
    PRE_BUF = 10
    ring = collections.deque(maxlen=PRE_BUF)
    triggered = False
    voiced_frames = []
    silence_frames = 0
    no_speech_frames = max(1, int(no_speech_s * 1000 / frame_ms))
    idle_frames = 0
    # ── Adaptif gürültü tabanı kalibrasyonu ──
    cal_frames_needed = max(3, int(calibration_s * 1000 / frame_ms))
    cal_energies = []          # ilk anlarda ölçülen ortam gürültüsü

    def _thresholds():
        """Gürültü tabanına göre dinamik eşikler.
        Sessiz oda (~40): sessiz<108, konuşma>188  (eski sabit davranışa yakın)
        Gürültülü oda (~300): sessiz<550, konuşma>1020 → TV/müzik konuşma sanılmaz"""
        noise = sorted(cal_energies)[len(cal_energies) // 2] if cal_energies else 60.0
        silent_thr = noise * 1.7 + 40
        speech_thr = max(170.0, noise * 3.2 + 60)
        return silent_thr, speech_thr

    # Silero VAD: durumlu (h/c) — her kayıtta sıfırla; 576 örnek pencere için tampon
    _silero_reset()
    roll = np.zeros(0, np.float32)
    _SIL_WIN = 576

    print("🎙️ Dinliyorum... konuş")

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", blocksize=frame_samples) as stream:
        for _ in range(int(max_seconds * 1000 / frame_ms)):
            data, overflowed = stream.read(frame_samples)
            if overflowed:
                continue
            pcm = data.tobytes()
            raw = np.frombuffer(pcm, dtype=np.int16)
            energy = np.abs(raw).mean()

            roll = np.concatenate([roll, raw.astype(np.float32) / 32768.0])
            if len(roll) > 2 * _SIL_WIN:
                roll = roll[-_SIL_WIN:]

            # Kalibrasyon aşaması: ortam gürültüsünü öğren
            # (ama çok yüksek enerji = kullanıcı hemen konuştu → kalibrasyona devam, tetikleme serbest)
            if len(cal_energies) < cal_frames_needed and energy < 400:
                cal_energies.append(energy)

            silent_thr, speech_thr = _thresholds()

            # Adaptif: tabana göre kesin sessizlik / kesin konuşma
            if energy < silent_thr:
                is_speech = False
            elif energy > speech_thr:
                is_speech = True
            else:
                # Orta bölge: önce Silero (en isabetli), yoksa webrtcvad
                sprob = _silero_prob(roll[-_SIL_WIN:]) if len(roll) >= _SIL_WIN else -1.0
                if sprob >= 0.0:
                    is_speech = sprob > 0.5
                else:
                    try:
                        is_speech = vad.is_speech(pcm, sample_rate)
                    except Exception:
                        is_speech = energy > (silent_thr + speech_thr) / 2

            if not triggered:
                ring.append((pcm, is_speech))
                # 30% speech → kayda başla
                num_voiced = sum(1 for _, s in ring if s)
                if num_voiced >= max(1, int(0.3 * ring.maxlen)):
                    triggered = True
                    for f, _ in ring:
                        voiced_frames.append(f)
                    ring.clear()
                else:
                    idle_frames += 1
                    # Konuşma hiç başlamadı → erken çık (boşa dinleme yok)
                    if idle_frames >= no_speech_frames:
                        st, sp = _thresholds()
                        print(f"🔇 Konuşma algılanmadı (gürültü~{sorted(cal_energies)[len(cal_energies)//2] if cal_energies else 0:.0f}, eşikler {st:.0f}/{sp:.0f}), çıkılıyor")
                        break
            else:
                voiced_frames.append(pcm)
                if not is_speech:
                    silence_frames += 1
                else:
                    silence_frames = 0
                if silence_frames >= num_silence_frames:
                    break

    if not voiced_frames:
        return np.array([], dtype=np.int16)

    audio = b"".join(voiced_frames)
    arr = np.frombuffer(audio, dtype=np.int16)
    return arr

def save_wav(path, audio: np.ndarray, sample_rate=16000):
    import soundfile as sf
    sf.write(path, audio, sample_rate)

def play_wav(path):
    try:
        import soundfile as sf
        import sounddevice as sd
        data, sr = sf.read(path)
        sd.play(data, sr)
        sd.wait()
    except Exception as e:
        print(f"play hatası: {e}")
        # fallback afplay / aplay
        import subprocess, platform, os
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["afplay", path], check=False)
            elif system == "Linux":
                subprocess.run(["aplay", path], check=False)
            elif system == "Windows":
                os.startfile(path)
        except Exception:
            pass
