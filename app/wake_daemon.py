"""
ELİŞA Wake Daemon — Siri gibi her zaman dinler
Masaüstündeyken "hey elisha" / "hey elişa" deyince ELİŞA'yı uyandırır.
Çalıştır: python3 app/wake_daemon.py  (arka planda)
Durdur: pkill -f wake_daemon
"""
import sys, time, subprocess, os, atexit
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

LOCK_FILE = Path("/tmp/elisha_wake_daemon.pid")

def acquire_lock() -> bool:
    """Tek authority: aynı anda yalnızca bir wake daemon çalışabilir."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"⚠️ Wake daemon zaten çalışıyor (PID {pid}). Bu süreç çıkıyor.")
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))
    return True

import numpy as np

ENABLE_TTS_WAKE_RESPONSE = True  # uyandığında "Buyurun" desin

def _blocked() -> bool:
    """ELİŞA konuşurken veya dinlerken wake tetiklenmesin
    (kendi sesini komut sanması = saçmalamanın ana kaynağı)."""
    return (Path("/tmp/elisha_tts_active").exists()
            or Path("/tmp/elisha_mic_active").exists())

def ensure_gui():
    """GUI yoksa başlat, varsa öne getir"""
    import subprocess, time, urllib.request
    # Önce sağlık kontrolü: server ayaktaysa GUI çalışıyordur
    try:
        urllib.request.urlopen("http://localhost:8765/api/health", timeout=1)
        try:
            subprocess.run(["osascript", "-e", 'tell application "Python" to activate'], timeout=2)
        except: pass
        return True
    except Exception:
        pass
    # Yok, başlat (venv python + doğru dosya adı)
    root = Path(__file__).parent.parent
    py = root / "venv" / "bin" / "python3"
    cmd = str(py) if py.exists() else "python3"
    try:
        subprocess.Popen([cmd, "-u", "app/desktop_app.py"], cwd=str(root), stdout=open("/tmp/elisa.log","a"), stderr=subprocess.STDOUT, start_new_session=True)
        print("GUI başlatıldı")
        time.sleep(3)
        return True
    except Exception as e:
        print(f"GUI başlatma hatası: {e}")
        return False

def speak(text):
    try:
        from elisha.orchestrator import ElishaOrchestrator
        # hızlı TTS için ayrı orchestrator değil, sadece TTS
        from elisha.config import load_config
        from elisha.tts.engine import TTSEngine
        cfg = load_config()
        tts = TTSEngine(cfg)
        tts.speak(text)
    except Exception as e:
        print(f"speak hatası: {e}")

def main():
    print("💫 ELİŞA Wake Daemon başladı — 'hey elisha' bekleniyor (Ctrl+C durdur)")
    print("   Masaüstünde, tarayıcıda, her yerde tetikler. %100 local.")
    from elisha.wakeword.detector import WakeWordDetector
    from elisha.config import load_config
    import sounddevice as sd
    import numpy as _np0
    _np0.seterr(all="ignore")  # whisper mel-spec overflow uyarılarını sustur

    cfg = load_config()
    # Kalıcılık: /tmp bayrağı reboot'ta silinir — ayarlara göre garantiye al
    try:
        from elisha import settings as _settings
        if _settings.get("wake_enabled", True):
            Path("/tmp/elisha_wake_enabled").write_text("1")
            print("✅ Wake bayrağı ayarlardan doğrulandı (kalıcı açık)")
    except Exception as e:
        print(f"wake bayrağı kontrol hatası: {e}")
    # wake word detector
    det = WakeWordDetector(cfg)
    print(f"Wake mod: {getattr(det,'_mode','?')}, words: {det.wake_words}")

    # Ollama hazır mı kontrol (ELİŞA beyin)
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            print("Ollama hazır")
        else:
            print("Ollama yok, mock ile devam")
    except:
        print("Ollama yok, mock ile devam")

    # openWakeWord modu: ultra hafif, sürekli dinleme (80ms chunk'lar)
    if getattr(det, '_mode', '') == "openwakeword":
        print("🎯 openWakeWord modu: sürekli 80ms chunk analizi (çok düşük CPU)")
        _run_openwakeword_loop(det, cfg)
    else:
        # STT fallback modu: 2.5s kayıt + whisper transcribe
        print("🎤 STT wake modu: 2.5s kayıt + whisper transcribe (daha yoğun CPU)")
        _run_stt_wake_loop(det, cfg)


def _run_openwakeword_loop(det, cfg):
    """HİBRİT wake:
    1) openWakeWord skoru eşiği aşarsa anında tetikle (İngilizce benzer sesler)
    2) Konuşma patlaması bitince tiny-whisper ile doğrula — Türkçe 'hey elişa'
       asıl yolu bu. CPU: sadece konuşma varken kısa transcribe."""
    import sounddevice as sd
    import time
    import numpy as _np

    sr = 16000
    chunk_samples = 1280  # 80ms @ 16kHz
    threshold = cfg.get("wakeword", {}).get("threshold", 0.5)

    consecutive_triggers = 0
    required_consecutive = 2

    # ── Semantic doğrulayıcı (tiny whisper, lazy) ──
    verifier = {"model": None}
    def _verify(audio_f32) -> tuple[bool, str]:
        try:
            if verifier["model"] is None:
                from faster_whisper import WhisperModel
                print("⏳ Wake doğrulayıcı yükleniyor (whisper tiny int8)...")
                verifier["model"] = WhisperModel("tiny", device="cpu", compute_type="int8")
                print("✅ Wake doğrulayıcı hazır")
            segments, _info = verifier["model"].transcribe(
                audio_f32, language="tr", beam_size=1,
                no_speech_threshold=0.45, temperature=0.0)
            text = " ".join(s.text for s in segments).strip()
            if not text:
                return False, ""
            ok = det.check_text_trigger(text)
            print(f"🔎 Wake doğrulama: '{text}' → {'TETİK' if ok else 'geç'}")
            return ok, text
        except Exception as e:
            print(f"doğrulama hatası: {e}")
            return False, ""

    # ── Konuşma patlaması takibi ──
    buffer = []           # float32 chunk listesi (konuşurken)
    silence_ms = 0
    speech_ms = 0
    was_speech = False
    ENERGY_ON = 0.012     # konuşma başlangıcı
    ENERGY_OFF = 0.007    # konuşma bitişi
    CHUNK_MS = 80

    def _fire(label, transcript=""):
        print(f"✨ WAKE TETİKLENDİ ({label})! {transcript[:60]}")
        ensure_gui()
        try:
            cmd = det.strip_wake_word(transcript) if transcript else ""
            Path("/tmp/elisha_wake").write_text(cmd)
        except Exception:
            pass
        time.sleep(6)  # kendi TTS'imizi duymasın

    while True:
        if not Path("/tmp/elisha_wake_enabled").exists() or _blocked():
            time.sleep(0.5)
            buffer = []; speech_ms = 0; silence_ms = 0; was_speech = False
            continue
        try:
            rec = sd.rec(chunk_samples, samplerate=sr, channels=1, dtype='float32')
            sd.wait()
            chunk = rec.flatten()
            energy = float(_np.sqrt(_np.mean(chunk ** 2)))

            # ── Yol 1: openWakeWord anlık skor (hafif, sürekli) ──
            pred = det._engine.predict(chunk)
            score = max(pred.values()) if pred else 0.0
            if score > threshold:
                consecutive_triggers += 1
                if consecutive_triggers >= required_consecutive:
                    det._engine.reset()
                    _fire(f"jarvis score={score:.2f}")
                    buffer = []; was_speech = False; speech_ms = 0
                    continue
            else:
                consecutive_triggers = 0

            # ── Yol 2: enerji segmentasyonu + semantic doğrulama ──
            if energy >= ENERGY_ON or (was_speech and energy > ENERGY_OFF):
                buffer.append(chunk)
                speech_ms += CHUNK_MS
                silence_ms = 0
                was_speech = True
            elif was_speech:
                silence_ms += CHUNK_MS
                buffer.append(chunk)
                if silence_ms >= 320:  # ~4 sessiz chunk = konuşma bitti
                    if speech_ms >= 500:  # çok kısa gürültüyü atla
                        audio = _np.concatenate(buffer)[: sr * 5]
                        triggered, txt = _verify(audio)
                        if triggered:
                            _fire("semantic", txt)
                    buffer = []
                    was_speech = False
                    speech_ms = 0
                    silence_ms = 0
            else:
                # tam sessizlik — buffer'ı taze tut (son 1sn kalsın)
                buffer.append(chunk)
                if len(buffer) > 12:
                    buffer = buffer[-12:]

        except KeyboardInterrupt:
            print("\nDaemon durdu")
            break
        except Exception as e:
            print(f"oww hata: {e}")
            time.sleep(0.5)


def _run_stt_wake_loop(det, cfg):
    """STT tabanlı fallback wake — her 2.5s'de whisper transcribe."""
    import sounddevice as sd
    import time

    consecutive = 0
    while True:
        if not Path("/tmp/elisha_wake_enabled").exists() or _blocked():
            time.sleep(0.5)
            continue
        try:
            sr = 16000
            dur = 2.5
            try:
                rec = sd.rec(int(dur*sr), samplerate=sr, channels=1, dtype='int16')
                sd.wait()
                audio = rec.flatten()
            except Exception as e:
                print(f"mic hatası: {e}")
                time.sleep(1)
                continue

            if np.abs(audio).mean() < 120:
                time.sleep(0.15)
                continue

            triggered, txt = det.detect_stt(audio, sr)
            if triggered:
                print(f"✨ TETİKLENDİ: '{txt}'")
                consecutive = 0
                ensure_gui()
                try:
                    Path("/tmp/elisha_wake").write_text(txt)
                except:
                    pass
                print("GUI komut dinliyor... 10 sn bekle")
                time.sleep(10)
                continue
            else:
                if txt and len(txt.strip()) > 2:
                    pass
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nDaemon durdu")
            break
        except Exception as e:
            print(f"daemon hata: {e}")
            time.sleep(0.8)

if __name__ == "__main__":
    if not acquire_lock():
        sys.exit(0)
    main()
