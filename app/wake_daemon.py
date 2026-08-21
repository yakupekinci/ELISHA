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

def ensure_gui():
    """GUI yoksa başlat, varsa öne getir"""
    import subprocess, time
    # pgrep ile kontrol
    try:
        out = subprocess.check_output(["pgrep", "-f", "app/desktop.py"], text=True)
        if out.strip():
            # var, öne getir (macOS)
            try:
                subprocess.run(["osascript", "-e", 'tell application "Python" to activate'], timeout=2)
            except: pass
            return True
    except: pass
    # yok, başlat
    try:
        subprocess.Popen(["nohup", "python3", "-u", "app/desktop.py"], cwd=str(Path(__file__).parent.parent), stdout=open("/tmp/elisa.log","a"), stderr=subprocess.STDOUT, start_new_session=True)
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
    print("   Masaüstünde, tarayıcıda, her yerde tetikler. %100 local, tiny değil small STT.")
    from elisha.wakeword.detector import WakeWordDetector
    from elisha.config import load_config
    import sounddevice as sd

    cfg = load_config()
    # wake word detector (lazy small)
    det = WakeWordDetector(cfg)
    # ilk tetikte model yüklenecek, biraz zaman alabilir
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

    consecutive = 0
    while True:
        # web'den kapatıldıysa dinleme
        if not Path("/tmp/elisha_wake_enabled").exists():
            time.sleep(1)
            continue
        try:
            sr = 16000
            dur = 2.5  # "hey elişa uyan" tam sığsın
            # kayıt
            try:
                rec = sd.rec(int(dur*sr), samplerate=sr, channels=1, dtype='int16')
                sd.wait()
                audio = rec.flatten()
            except Exception as e:
                print(f"mic hatası: {e}")
                time.sleep(1)
                continue

            if np.abs(audio).mean() < 120:  # düşük eşik — fısıltıyı da yakala
                time.sleep(0.15)
                continue

            triggered, txt = det.detect_stt(audio, sr)
            if triggered:
                print(f"✨ TETİKLENDİ: '{txt}'")
                consecutive = 0
                # GUI'yi uyandır
                ensure_gui()
                # tetik dosyası oluştur (GUI poll ederse)
                try:
                    Path("/tmp/elisha_wake").write_text(txt)
                except: pass
                # sesli karşılık
                # web hallediyor, daemon sessiz kalsın (çift ses olmasın)
                # if ENABLE_TTS_WAKE_RESPONSE:
                #     speak("Buyurun, sizi dinliyorum")
                print("GUI komut dinliyor... 10 sn bekle (web hallediyor)")
                time.sleep(10)
                # sonra tekrar wake dinlemeye devam
                continue
            else:
                # ara sıra log (spam olmasın)
                if txt and len(txt.strip())>2:
                    # print(f"duydu: {txt}")
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
