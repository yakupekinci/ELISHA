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

def record_until_silence(
    sample_rate=16000,
    vad_aggressiveness=2,
    silence_ms=900,
    max_seconds=8,
    frame_ms=30,
):
    """
    Mikrofonu dinle, konuşma bitene (sessizlik) kadar kaydet.
    webrtcvad ile sessizlik tespiti.
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

    print("🎙️ Dinliyorum... konuş")

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", blocksize=frame_samples) as stream:
        for _ in range(int(max_seconds * 1000 / frame_ms)):
            data, overflowed = stream.read(frame_samples)
            if overflowed:
                continue
            pcm = data.tobytes()
            raw = np.frombuffer(pcm, dtype=np.int16)
            energy = np.abs(raw).mean()

            # Çok sessizse (arka plan gürültüsü ~0-80) → kesinlikle sessizlik
            if energy < 80:
                is_speech = False
            # Güçlü konuşma sesi (MacBook Air ~200+) → kesinlikle konuşma
            elif energy > 200:
                is_speech = True
            else:
                # Orta bölge (80-200): VAD'a bırak
                try:
                    is_speech = vad.is_speech(pcm, sample_rate)
                except Exception:
                    is_speech = energy > 150

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
