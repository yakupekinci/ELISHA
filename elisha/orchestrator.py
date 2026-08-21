import re
import numpy as np
from .config import load_config
from .stt.engine import STTEngine
from .tts.engine import TTSEngine
from .llm.engine import LLMEngine
from .wakeword.detector import WakeWordDetector
from .skills.registry import SkillRegistry

class ElishaOrchestrator:
    def __init__(self, config_path=None):
        self.config = load_config(config_path)
        self.stt = STTEngine(self.config)
        self.tts = TTSEngine(self.config)
        self.llm = LLMEngine(self.config)
        self.wakeword = WakeWordDetector(self.config)
        self.skills = SkillRegistry(self.config)
        self.name = self.config.get("assistant", {}).get("name", "ELİŞA")

    def process_text(self, text: str) -> str:
        """
        Text -> LLM -> skills -> final text
        (STT bypass için, test ve Android için kullanılır)
        """
        if not text or not text.strip():
            return ""
        # wake word temizle
        if self.wakeword.check_text_trigger(text):
            text = self.wakeword.strip_wake_word(text)
            if not text:
                return "Efendim? Seni dinliyorum."

        print(f"👤 Kullanıcı: {text}")
        llm_raw = self.llm.chat(text)
        print(f"🧠 LLM ham: {llm_raw[:400]}")
        clean, skill_results = self.skills.handle_text(llm_raw)

        # Fallback: LLM eylem üretmediyse ama kullanıcı açıkça sistem komutu verdiyse mock kuralları dene
        if not skill_results:
            fallback = self._fallback_skill(text)
            if fallback:
                print(f"🔄 Fallback skill: {fallback[:100]}")
                clean2, skill_results2 = self.skills.handle_text(fallback)
                if skill_results2:
                    # LLM cevabını fallback ile birleştir
                    if clean and len(clean) > 5 and "Asistan:" not in clean:
                        clean = clean
                    else:
                        clean = clean2
                    skill_results = skill_results2

        # skill sonuçlarını cevaba ekle
        final = clean
        if skill_results:
            # eğer clean boşsa sadece skill sonucu göster
            if not clean or len(clean) < 5:
                final = "\n".join(skill_results)
            else:
                final = clean + "\n" + "\n".join(skill_results)

        final = final.strip()
        if not final:
            final = llm_raw.strip() or "Bir şey diyemedim."

        print(f"🤖 ELİŞA: {final}")
        return final

    def speak(self, text: str):
        self.tts.speak(text)

    def listen_once(self, use_vad=True) -> str:
        """
        Mikrofonu dinle ve text döndür (STT)
        """
        try:
            from .audio import record_until_silence
            import numpy as np
            audio = record_until_silence(
                sample_rate=self.config.get("audio", {}).get("sample_rate", 16000),
                vad_aggressiveness=self.config.get("audio", {}).get("vad_aggressiveness", 2),
                silence_ms=self.config.get("audio", {}).get("silence_threshold_ms", 900),
                max_seconds=self.config.get("audio", {}).get("record_seconds", 6),
            )
            if len(audio) == 0:
                return ""
            # wake word audio check (opsiyonel)
            # if self.wakeword.enabled and not self.wakeword.detect(audio):
            #     return ""
            text = self.stt.transcribe(audio)
            return text
        except Exception as e:
            print(f"Dinleme hatası: {e}")
            return ""

    def run_voice_loop(self):
        """
        Sonsuz döngü: dinle -> işle -> konuş
        Ctrl+C ile çık
        """
        print(f"🎧 {self.name} sesli döngü başladı. Konuşmak için mikrofonu kullan.")
        print("İpucu: 'Eleşa, Chrome'u aç' gibi dene. Çıkmak için Ctrl+C")
        # açılış
        self.speak(f"Merhaba, ben {self.name}. Seni dinliyorum.")

        try:
            while True:
                text = self.listen_once()
                if not text:
                    # STT mock ise klavyeden al
                    if self.stt.provider == "mock":
                        try:
                            text = input("\n⌨️ Yaz (mock STT): ").strip()
                            if text.lower() in ["çık", "exit", "quit", "kapat"]:
                                break
                        except (EOFError, KeyboardInterrupt):
                            break
                    else:
                        print("… ses algılanamadı, tekrar deniyorum")
                        continue
                if not text:
                    continue
                print(f"📝 STT: {text}")
                # wake word text fallback
                if self.wakeword.enabled and "elişa" not in text.lower() and "elisha" not in text.lower():
                    # wake word bekleniyor ama yoksa da devam et (V1'de katı değil)
                    pass

                response = self.process_text(text)
                self.speak(response)
        except KeyboardInterrupt:
            print("\n👋 Görüşürüz!")
            self.speak("Görüşürüz!")

    def _fallback_skill(self, text: str) -> str:
        """LLM eylem üretmediyse mock kuralları dene"""
        try:
            # LLMEngine'in mock mantığını yeniden kullan (kopya değil, direkt çağır)
            # Geçici olarak provider mock gibi davran
            from elisha.llm.engine import LLMEngine
            # Sadece skill tespiti için mock chat
            # hack: llm._chat_mock direkt çağrılabilir
            return self.llm._chat_mock(text)
        except Exception:
            return ""

    def run_cli_once(self, text: str, speak=False) -> str:
        resp = self.process_text(text)
        if speak:
            self.speak(resp)
        return resp
