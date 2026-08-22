import re
import numpy as np
from .config import load_config
from .stt.engine import STTEngine
from .tts.engine import TTSEngine
from .llm.engine import LLMEngine
from .wakeword.detector import WakeWordDetector
from .skills.registry import SkillRegistry
from .log import log, err


def _turkish_persona_fix(text: str) -> str:
    """
    qwen2.5:7b Türkçe'de resmi 'siz' formu kullanıyor ve kendini
    'yapay zeka' olarak tanıtıyor. Bu fonksiyon ELİŞA kişiliğine göre düzeltir.
    """
    if not text:
        return text

    # Türkçe, Latin ve yaygın noktalama dışındaki garip Unicode karakterleri temizle
    # (Çince, Vietnamca, Arapça harf aksan işaretleri vb. model hatası)
    import unicodedata
    allowed = set()
    cleaned = []
    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        # İzin verilenler: temel Latin (0-127), Latince ek (128-591), Türkçe özel
        # noktalama, rakam, boşluk
        if cp <= 591 or ch in 'şŞğĞıİöÖüÜçÇ…–—•·':
            cleaned.append(ch)
        elif cat in ('Zs', 'Pd', 'Po', 'Ps', 'Pe'):  # boşluk, tire, noktalama
            cleaned.append(ch)
        else:
            cleaned.append(' ')  # bilinmeyen → boşlukla değiştir
    text = re.sub(r' {2,}', ' ', ''.join(cleaned)).strip()

    # "Ben bir yapay zekayım / AI'yım / asistanım" → ELİŞA olarak tanıt
    text = re.sub(
        r'\bBen bir (yapay zeka|yapay-zeka|AI|asistan|dil modeli|büyük dil modeli)(y?[ıiuü]m|yım|yim|yum|yüm)\b',
        'Ben ELİŞA', text, flags=re.IGNORECASE
    )
    text = re.sub(
        r'\b(Bir )?(yapay zeka|AI|asistan|dil modeli) olarak\b',
        'ELİŞA olarak', text, flags=re.IGNORECASE
    )

    # Resmi → samimi: siz/size/sizi/sizin/sizinle → sen/sana/seni/senin/seninle
    replacements = [
        # Nesne/yön/bulunma/ayrılma ekleri (tek başına)
        (r'\bsize\b',              'sana'),
        (r'\bsizi\b',              'seni'),
        (r'\bsizin\b',             'senin'),
        (r'\bsizde\b',             'sende'),
        (r'\bsizden\b',            'senden'),
        (r'\bsizinle\b',           'seninle'),
        (r'\bSize\b',              'Sana'),
        (r'\bSizi\b',              'Seni'),
        (r'\bSizin\b',             'Senin'),
        # Özne
        (r'\bsiz\b',               'sen'),
        (r'\bSiz\b',               'Sen'),
        # 2. çoğul kişi ekleri: -(n)ız/-(n)iz/-(n)uz/-(n)üz + durum ekleri
        (r'nız(?=[a-züşğıöçâîû])', 'n'),   # nıza → na, nızda → nda, nızı → nı
        (r'niz(?=[a-züşğıöçâîû])', 'n'),
        (r'nuz(?=[a-züşğıöçâîû])', 'n'),
        (r'nüz(?=[a-züşğıöçâîû])', 'n'),
        (r'nız\b',                  'n'),
        (r'niz\b',                  'n'),
        (r'nuz\b',                  'n'),
        (r'nüz\b',                  'n'),
        # -(i/ı/u/ü)nız/niz ekleri (isim+iyelik+çoğul) → tekil
        (r'inize\b',               'ine'),
        (r'ınıza\b',               'ına'),
        (r'unuza\b',               'una'),
        (r'ünüze\b',               'üne'),
        (r'inizi\b',               'ini'),
        (r'ınızı\b',               'ını'),
        (r'ununuz\b',              'unun'),
        # Fiil sonları: -siniz/-sunuz/-sünüz/-şiniz
        (r'siniz\b',               'sin'),
        (r'sunuz\b',               'sun'),
        (r'sünüz\b',               'sün'),
        (r'şiniz\b',               'şin'),
        # Çoğul emir: -in/-ın/-un/-ün (kısa emir çoğulu)
        (r'\bbildir(?:in)\b',      'bildir'),
        (r'\byazın\b',             'yaz'),
        # (r'\bsorun\b', 'sor'),  # KALDIRILDI: "sorun"=problem anlamı var, çakışır
        # Yaygın kelimeler
        (r'\bihtiyacınız\b',       'ihtiyacın'),
        (r'\bihtiyacınıza\b',      'ihtiyacına'),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)

    return text.strip()

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
        from .memory import MemoryStore
        mem_cfg = self.config.get("memory", {}) or {}
        self.memory = MemoryStore(self.config) if mem_cfg.get("enabled", True) else None
        if self.memory is not None:
            n = self.memory.count_memories()
            log("MEMORY", f"🧠 {self.memory.db_path} ({n} kayıt)")
        from .tools import build_default_registry
        registry = build_default_registry(self.config, self.memory)
        self.registry = registry
        self._need_confirm_cls = NeedConfirmation
        self.permissions = PermissionManager(self.config)
        self.fastpath = FastPath(self.config, registry, self.memory,
                                 on_status=self._emit_status,
                                 permissions=self.permissions)
        agent_cfg = self.config.get("agent", {}) or {}
        # Agent: tool calling destekleyen herhangi bir provider varsa aktif et
        tool_provider = self.llm.router.get_provider(needs_tools=True)
        if agent_cfg.get("enabled", True) and tool_provider:
            try:
                from .agent import AgentLoop
                self.agent = AgentLoop(
                    self.config,
                    self.llm.host,
                    self.llm.model,
                    registry,
                    on_status=self._emit_status,
                    permissions=self.permissions,
                    memory_store=self.memory,
                    provider=tool_provider,
                )
                log("AGENT", f"🤖 açık ({len(registry.names())} araç, max {self.agent.max_steps} adım, provider={tool_provider.name})")
            except Exception as e:
                err(f"agent başlatılamadı, V1 fallback kullanılacak: {e}")
                self.agent = None
        self._restore_session()

    def _restore_session(self):
        """Restart sonrası son konuşmaları ve hafızayı geri yükle."""
        if self.memory is None:
            return
        try:
            recent = self.memory.recent_messages(limit=30)
            if recent:
                self.llm.history = [{"role": r["role"], "content": r["content"]} for r in recent]
                log("MEMORY", f"💬 oturum geri yüklendi ({len(recent)} mesaj)")
        except Exception as e:
            err(f"oturum geri yüklenemedi: {e}")

    def _emit_status(self, text: str):
        log("STT", f"⏳ {text}")
        cb = getattr(self, "status_callback", None)
        if cb:
            try:
                cb(text)
            except Exception:
                pass

    def _remember_turn(self, user_text: str, assistant_text: str):
        self.llm.history.append({"role": "user", "content": user_text})
        self.llm.history.append({"role": "assistant", "content": assistant_text})
        if len(self.llm.history) > 30:
            self.llm.history = self.llm.history[-30:]
        if self.memory is not None:
            try:
                self.memory.save_message("user", user_text)
                self.memory.save_message("assistant", assistant_text)
            except Exception as e:
                err(f"konuşma kaydedilemedi: {e}")

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

        # Sadece çok kısa uyandırma/tetik kelimelerini kısa devre yap
        # Gerisi (nasılsın, merhaba + soru) LLM'e gitsin — daha doğal cevap verir
        t_lower = text.lower().strip()
        _WAKE_ONLY = {"uyan", "hey", "elişa", "elisha", "hey elişa", "hey elisha"}
        if t_lower in _WAKE_ONLY:
            return "Buradayım, seni dinliyorum."

        log("USER", f"👤 {text}")

        # GÜVENLİK: bekleyen onay varsa önce onu çöz
        if self.permissions.has_pending():
            pending_q = self.permissions.pending["question"] if self.permissions.pending else ""
            result = self.permissions.resolve(self.registry, text)
            if result is not None:
                answer = result.message or ("Tamam, yaptım." if result.success else f"Yapamadım: {result.error}")
                log("SECURITY", f"onay sonucu: {answer[:120]}")
                self._remember_turn(text, answer)
                return answer
            # cevap evet/hayır değilse hatırlat ve normal akışa devam etme
            reminder = f"Onay bekliyor: {pending_q} (evet / hayır)"
            log("SECURITY", reminder)
            return reminder

        # V2.1: deterministik hızlı yol — yaygın komutlar LLM'siz anında çalışır
        if self.fastpath is not None:
            fast = None
            try:
                fast = self.fastpath.try_route(text)
            except self._need_confirm_cls as nc:
                # hızlı yol HIGH/CRITICAL araca çarptı -> onay akışı
                log("SECURITY", f"hızlı yol onay istendi: {nc.message}")
                self._remember_turn(text, nc.message)
                return nc.message
            except Exception as e:
                err(f"hızlı yol hatası ({e}), agent'a düşülüyor")
            if fast:
                log("FASTPATH", f"⚡ {fast[:120]}")
                self.llm.history.append({"role": "user", "content": text})
                self.llm.history.append({"role": "assistant", "content": fast})
                if len(self.llm.history) > 10:
                    self.llm.history = self.llm.history[-10:]
                log("CHAT", f"🤖 {fast}")
                return fast

        # V2.2: basit selamlamalar/sohbet → doğrudan LLM (tool'suz, hızlı)
        # Agent loop 21 tool tanımını gönderir → token israfı + yavaş
        # Selamlamaları direkt Groq/Gemini'ye yollayıp doğal cevap alıyoruz
        if self._is_smalltalk(t_lower):
            log("SMALLTALK", f"💬 sohbet modunda yanıtlanıyor (tool'suz)")
            reply = self.llm.chat(text)
            if reply:
                reply = _turkish_persona_fix(reply)
                self._remember_turn(text, reply)
                log("CHAT", f"🤖 {reply}")
                return reply

        # V2: gerçek agent döngüsü (native tool calling)
        if self.agent is not None:
            try:
                result = self.agent.run(text, history=list(self.llm.history))
                final = (result.final_text or "").strip()
                if final:
                    final = _turkish_persona_fix(final)
                    self._remember_turn(text, final)
                    log("CHAT", f"🤖 {final}")
                    return final
                log("AGENT", "boş döndü, V1 fallback'e düşülüyor")
            except self._need_confirm_cls as nc:
                log("SECURITY", f"agent onay istedi: {nc.message}")
                self._remember_turn(text, nc.message)
                return nc.message
            except Exception as e:
                err(f"agent hatası ({e}), V1 fallback'e düşülüyor")

        # V1 fallback: regex [ACTION] sistemi
        llm_raw = self.llm.chat(text)
        log("LLM", f"🧠 ham: {llm_raw[:200]}")
        clean, skill_results = self.skills.handle_text(llm_raw)

        meaningful = clean and len(clean.strip()) >= 5 and "Asistan:" not in clean
        if not skill_results and not meaningful:
            fallback = self._fallback_skill(text)
            if fallback:
                log("SKILL", f"🔄 fallback: {fallback[:100]}")
                clean2, skill_results2 = self.skills.handle_text(fallback)
                if skill_results2:
                    clean = clean2
                    skill_results = skill_results2

        final = clean
        if skill_results:
            if not clean or len(clean) < 5:
                final = "\n".join(skill_results)
            else:
                final = clean + "\n" + "\n".join(skill_results)

        final = final.strip()
        if not final:
            final = llm_raw.strip() or "Bir şey diyemedim."

        final = _turkish_persona_fix(final)
        log("CHAT", f"🤖 {final}")
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
            err(f"dinleme hatası: {e}")
            return ""

    def run_voice_loop(self):
        """
        Sonsuz döngü: dinle -> işle -> konuş
        Ctrl+C ile çık
        """
        print(f"🎧 {self.name} sesli döngü başladı.")
        print("   Konuş — ses algılandığında otomatik kaydedilir ve işlenir.")
        print("   Çıkmak için Ctrl+C\n")
        self.speak(f"Merhaba, ben {self.name}. Seni dinliyorum.")

        _silent_count = 0
        try:
            while True:
                text = self.listen_once()
                if not text:
                    if self.stt.provider == "mock":
                        try:
                            text = input("\n⌨️ Yaz (mock STT): ").strip()
                            if text.lower() in ["çık", "exit", "quit", "kapat"]:
                                break
                        except (EOFError, KeyboardInterrupt):
                            break
                    else:
                        _silent_count += 1
                        if _silent_count % 3 == 0:
                            print("   (ses algılanamadı — mikrofona konuş)")
                        continue
                _silent_count = 0
                if not text:
                    continue
                log("STT", f"📝 Duydum: {text}")
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

    @staticmethod
    def _is_smalltalk(text_lower: str) -> bool:
        """Basit selamlamaları ve sohbet cümlelerini algıla.
        
        Bunlar agent'a (21 tool ile) gönderilmemeli — doğrudan LLM'e
        tool'suz giderse hem daha hızlı hem daha doğal cevap verir.
        """
        t = text_lower.strip()
        # Çok uzun cümleler sohbet değil, muhtemelen karmaşık istek
        if len(t) > 80:
            return False
        
        # Doğrudan selamlama kalıpları
        _GREETINGS = {
            "merhaba", "selam", "selamlar", "günaydın", "gunaydin",
            "iyi akşamlar", "iyi aksamlar", "iyi geceler",
            "iyi günler", "iyi gunler", "hayırlı sabahlar",
            "naber", "nbr", "ne haber", "napıyorsun", "napiyon",
            "hoş geldin", "hos geldin", "hoşgeldin",
        }
        if t in _GREETINGS:
            return True
        
        # Sohbet/hal hatır kalıpları (regex)
        _SMALLTALK_PATTERNS = [
            r"^(merhaba|selam|günaydın|iyi (akşam|gece|gün)ler?)\b",
            r"^nasılsın\b", r"^nasilsin\b", r"^nasıl gidiyor\b",
            r"^ne yapıyorsun\b", r"^ne yapiyorsun\b",
            r"^iyisin\b", r"^iyi misin\b",
            r"^teşekkür", r"^tesekkur", r"^sağ ?ol\b", r"^eyvallah\b",
            r"^görüşürüz\b", r"^gorusuruz\b", r"^hoşça ?kal\b",
            r"^iyi geceler\b", r"^bay bay\b", r"^bye\b",
            r"^canın sağ ?olsun\b", r"^olsun\b",
            r"^tamam\b$", r"^ok\b$", r"^anladım\b$",
            r"^seni seviyorum\b", r"^çok teşekkürler\b",
            r"^adın ne", r"^sen kimsin",
        ]
        import re as _re
        for pat in _SMALLTALK_PATTERNS:
            if _re.search(pat, t):
                # Ama eğer sonrasında komut belirtisi varsa sohbet değil
                # ör: "merhaba chrome aç" → komut, sohbet değil
                _COMMAND_HINTS = ["aç", "kapat", "çal", "sil", "oluştur", "ara",
                                  "yap", "göster", "listele", "oku", "yaz", "indir"]
                if any(h in t for h in _COMMAND_HINTS):
                    return False
                return True
        
        return False

    def run_cli_once(self, text: str, speak=False) -> str:
        resp = self.process_text(text)
        if speak:
            self.speak(resp)
        return resp
