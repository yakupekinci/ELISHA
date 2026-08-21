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
        self.status_callback = None
        self.agent = None
        self.fastpath = None
        from .fastpath import FastPath
        from .security import PermissionManager, NeedConfirmation
        from .tools import build_default_registry
        registry = build_default_registry(self.config)
        self.registry = registry
        self.permissions = PermissionManager(self.config)
        self._need_confirm_cls = NeedConfirmation
        self.fastpath = FastPath(self.config, registry)
        agent_cfg = self.config.get("agent", {}) or {}
        if agent_cfg.get("enabled", True) and self.llm.provider == "ollama":
            try:
                from .agent import AgentLoop
                self.agent = AgentLoop(
                    self.config,
                    self.llm.host,
                    self.llm.model,
                    registry,
                    on_status=self._emit_status,
                    permissions=self.permissions,
                )
                print(f"🤖 Agent modu açık ({len(registry.names())} araç, max {self.agent.max_steps} adım)")
            except Exception as e:
                print(f"⚠️ Agent başlatılamadı, eski sisteme düşülüyor: {e}")
                self.agent = None

    def _emit_status(self, text: str):
        print(f"   ⏳ {text}")
        cb = getattr(self, "status_callback", None)
        if cb:
            try:
                cb(text)
            except Exception:
                pass

    def _remember_turn(self, user_text: str, assistant_text: str):
        self.llm.history.append({"role": "user", "content": user_text})
        self.llm.history.append({"role": "assistant", "content": assistant_text})
        if len(self.llm.history) > 10:
            self.llm.history = self.llm.history[-10:]

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

        # GÜVENLİK: bekleyen onay varsa önce onu çöz
        if self.permissions.has_pending():
            pending_q = self.permissions.pending["question"] if self.permissions.pending else ""
            result = self.permissions.resolve(self.registry, text)
            if result is not None:
                answer = result.message or ("Tamam, yaptım." if result.success else f"Yapamadım: {result.error}")
                print(f"🔐 Onay sonucu: {answer[:120]}")
                self._remember_turn(text, answer)
                return answer
            # cevap evet/hayır değilse hatırlat ve normal akışa devam etme
            reminder = f"Onay bekliyor: {pending_q} (evet / hayır)"
            print(f"🔐 {reminder}")
            return reminder

        # V2.1: deterministik hızlı yol — yaygın komutlar LLM'siz anında çalışır
        if self.fastpath is not None:
            try:
                fast = self.fastpath.try_route(text)
                if fast:
                    print(f"⚡ Hızlı yol: {fast[:120]}")
                    self.llm.history.append({"role": "user", "content": text})
                    self.llm.history.append({"role": "assistant", "content": fast})
                    if len(self.llm.history) > 10:
                        self.llm.history = self.llm.history[-10:]
                    print(f"🤖 ELİŞA: {fast}")
                    return fast
            except Exception as e:
                print(f"⚠️ Hızlı yol hatası ({e}), agent'a düşülüyor")

        # V2: gerçek agent döngüsü (native tool calling)
        if self.agent is not None:
            try:
                result = self.agent.run(text, history=list(self.llm.history))
                final = (result.final_text or "").strip()
                if final:
                    self._remember_turn(text, final)
                    print(f"🤖 ELİŞA: {final}")
                    return final
                print("⚠️ Agent boş döndü, eski sisteme düşülüyor")
            except self._need_confirm_cls as nc:
                print(f"🔐 Onay istendi: {nc.message}")
                self._remember_turn(text, nc.message)
                return nc.message
            except Exception as e:
                print(f"⚠️ Agent hatası ({e}), eski sisteme düşülüyor")

        # V1 fallback: regex [ACTION] sistemi
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
