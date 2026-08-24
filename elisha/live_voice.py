"""ELİŞA Gemini Live — gerçek zamanlı sesli sohbet (Mark-LI 'Real-time Voice' muadili).
"hey elişa" sonrası klasik zincir (STT→LLM→TTS ~6sn) yerine CANLI oturum açar:
mikrofon sürekli akar, model anında (<1sn) sesle yanıt verir, sırayla konuşulur.

Ayarlar: live_mode (true), live_model (gemini-2.0-flash-live-001), live_voice (Aoede).
Herhangi bir hata klasik zincire düşer — asistan asla sessiz kalmaz.
"""
import asyncio
import queue
import threading
import time

from . import settings
from .log import log

_STOP_WORDS = ("kapat kendini", "görüşürüz", "kendini kapat", "uyku moduna geç",
               "artık yeter")
_MAX_SESSION_S = 300          # tek oturum üst sınırı (güvenlik)
_active = False               # şu an canlı oturum sürüyor mu


def is_active() -> bool:
    return _active


def _sys_instruction() -> str:
    try:
        from .persona_agent import build_system_prompt
        p = build_system_prompt()
        if p:
            return p[:4000]
    except Exception:
        pass
    return ("Sen ELİŞA'sın, kullanıcının Mac asistanısın. Türkçe konuş. "
            "Samimi, kısa ve doğal cevap ver; sesli sohbet ediyorsunuz.")


def _get_key() -> str:
    import os
    return os.getenv("GEMINI_API_KEY") or str(settings.get("gemini_api_key") or "")


def run_session(on_state=None) -> bool:
    """Tek canlı oturum çalıştırır (bloklamaz — kendi thread'inde çağrılır).
    on_state('listening'|'speaking') HUD görselleri için. Dönüş: başarı mı."""
    key = _get_key()
    if not key:
        log("LIVE", "anahtar yok — klasik zincir")
        return False
    global _active
    result = {"ok": False}

    def runner():
        global _active
        try:
            _active = True
            asyncio.run(_async_session(key, result, on_state))
        except Exception as e:
            log("LIVE", f"oturum hatası: {e}")

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=_MAX_SESSION_S + 30)
    _active = False
    return result["ok"]


async def _async_session(key: str, result: dict, on_state):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    model = str(settings.get("live_model") or "gemini-2.5-flash-native-audio-latest")
    voice = str(settings.get("live_voice") or "Aoede")

    cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=_sys_instruction(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        input_audio_transcription=types.AudioTranscriptionConfig(),
    )

    import numpy as np
    import sounddevice as sd

    out_stream = sd.RawOutputStream(samplerate=24000, channels=1, dtype="int16",
                                    blocksize=0, callback=None)
    # Basit ve dayanıklı: gelen PCM'i doğrudan yaz
    out_stream.start()

    mic_q: "queue.Queue[bytes]" = queue.Queue()
    stop_evt = threading.Event()

    def mic_cb(indata, frames, ti, status):
        if not stop_evt.is_set():
            mic_q.put(bytes(indata))

    mic = sd.RawInputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=1600, callback=mic_cb)

    async def mic_pump(session):
        loop = asyncio.get_event_loop()
        while True:
            chunk = await loop.run_in_executor(None, mic_q.get)
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))

    async def recv_pump(session):
        said_bye = False
        async for msg in session.receive():
            sc = getattr(msg, "server_content", None)
            # Kullanıcının sözünü yazıya dök → bitirme komutu ara
            if sc and sc.input_transcription and sc.input_transcription.text:
                txt = sc.input_transcription.text.lower().strip()
                if any(w in txt for w in _STOP_WORDS):
                    said_bye = True
            # Modelin sesini hoparlöre akıt
            if msg.data:
                if on_state:
                    try:
                        on_state("speaking")
                    except Exception:
                        pass
                await asyncio.get_event_loop().run_in_executor(
                    None, out_stream.write, msg.data)
            if said_bye:
                return True
        return said_bye

    mic.start()
    log("LIVE", f"🔴 canlı oturum açılıyor ({model}, ses={voice})")
    try:
        async with client.aio.live.connect(model=model, config=cfg) as session:
            if on_state:
                try:
                    on_state("listening")
                except Exception:
                    pass
            recv_task = asyncio.create_task(recv_pump(session))
            pump_task = asyncio.create_task(mic_pump(session))
            done, pending = await asyncio.wait({recv_task}, timeout=_MAX_SESSION_S,
                                               return_when=asyncio.FIRST_COMPLETED)
            stop_evt.set()
            for p_ in pending:
                p_.cancel()
            if done and recv_task.result():
                log("LIVE", "👋 kullanıcı oturumu kapattı")
            result["ok"] = True
    finally:
        try:
            mic.stop(); mic.close()
        except Exception:
            pass
        try:
            out_stream.stop(); out_stream.close()
        except Exception:
            pass


def is_enabled() -> bool:
    return str(settings.get("live_mode", True)) not in ("0", "false", "False") \
           and bool(_get_key())
