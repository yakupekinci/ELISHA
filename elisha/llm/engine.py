import re
import requests
from elisha.persona import PERSONA_TR, SKILL_PROMPT_TR

class LLMEngine:
    def __init__(self, config: dict):
        self.config = config
        self.provider = (config.get("llm", {}).get("provider") or "auto").lower()
        self.model = config.get("llm", {}).get("model", "qwen2.5:7b")
        self.fallback_model = config.get("llm", {}).get("fallback_model", "qwen2.5:1.5b")
        self.host = config.get("llm", {}).get("host", "http://localhost:11434")
        self.system_prompt = config.get("llm", {}).get("system_prompt", PERSONA_TR) + "\n" + SKILL_PROMPT_TR
        self.temperature = config.get("llm", {}).get("temperature", 0.7)
        self.max_tokens = config.get("llm", {}).get("max_tokens", 512)
        self.history = []
        self._init_engine()

    def _init_engine(self):
        if self.provider == "auto":
            if self._ollama_available():
                self.provider = "ollama"
                self._select_best_model()
            else:
                self.provider = "mock"
                print("⚠️ LLM: mock mod (Ollama yok, kural tabanlı cevap)")
        elif self.provider == "ollama":
            if not self._ollama_available():
                print("⚠️ Ollama bağlanamadı, mock moda geçiliyor")
                self.provider = "mock"
            else:
                self._select_best_model()

    def _select_best_model(self):
        """En iyi mevcut modeli seç: büyük varsa onu, yoksa fallback."""
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            available = [m["name"] for m in r.json().get("models", [])]
            if self.model in available:
                print(f"✅ LLM: Ollama ({self.model}) — akıllı mod")
            elif self.fallback_model in available:
                print(f"⚠️ LLM: {self.model} yok, fallback → {self.fallback_model}")
                self.model = self.fallback_model
            elif available:
                self.model = available[0]
                print(f"⚠️ LLM: tercih edilen modeller yok, {self.model} kullanılıyor")
            else:
                print(f"⚠️ LLM: hiç model yok! 'ollama pull {self.model}' çalıştır")
        except Exception:
            print(f"✅ LLM: Ollama ({self.model}) hazır (model listesi alınamadı)")

    def _ollama_available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, user_text: str) -> str:
        # Saat/tarih gibi kesin bilgiler için LLM'i atla, gerçek zamanı döndür
        t_low = user_text.lower()
        if any(k in t_low for k in ["saat kaç", "tarih ne", "günlerden ne"]):
            import datetime
            now = datetime.datetime.now().strftime("%H:%M, %d %B %Y")
            resp = f"Şu an saat {now}."
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": resp})
            if len(self.history) > 10:
                self.history = self.history[-10:]
            return resp

        # geçmişe ekle
        self.history.append({"role": "user", "content": user_text})
        # keep last 10 turns
        if len(self.history) > 10:
            self.history = self.history[-10:]

        if self.provider == "ollama":
            resp = self._chat_ollama(user_text)
        else:
            resp = self._chat_mock(user_text)

        self.history.append({"role": "assistant", "content": resp})
        return resp

    def _chat_ollama(self, user_text: str) -> str:
        try:
            # Ollama /api/chat
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    *self.history[:-1],  # zaten ekledik, son user hariç tekrar eklememek için
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            }
            # history'de son user zaten var, duplicate olmasın
            # Bu yüzden messages'i yeniden kur
            msgs = [{"role": "system", "content": self.system_prompt}]
            for h in self.history:
                msgs.append(h)
            payload["messages"] = msgs

            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            text = data.get("message", {}).get("content", "") or data.get("response", "")
            return text.strip() or "Bir şey diyemedim, tekrar eder misin?"
        except Exception as e:
            print(f"Ollama hatası: {e} -> mock fallback")
            return self._chat_mock(user_text)

    def _chat_mock(self, user_text: str) -> str:
        """
        Kural tabanlı Türkçe cevap - model olmadan bile sistem kontrol çalışsın
        """
        t = user_text.lower().strip()

        # 1) Dosya oluştur - en öncelikli (içerik selam içerse bile)
        if any(w in t for w in ["dosya oluştur", "not oluştur", "dosya yap", "not al", "txt oluştur"]) or ("oluştur" in t and (".txt" in t or "not" in t or "dosya" in t)):
            m_path = re.search(r"(\S+\.txt|\S+\.md)", t)
            path = "~/Desktop/elisha-not.txt"
            if m_path:
                fname = m_path.group(1)
                if "/" not in fname:
                    path = f"~/Desktop/{fname}"
                else:
                    path = fname
            m_content = re.search(r"içeriği?\s*(.+?)(?:\s*olsun)?$", t)
            content = "ELİŞA tarafından oluşturuldu"
            if m_content:
                content = m_content.group(1).strip()[:200]
                if len(content) < 2:
                    content = "ELİŞA tarafından oluşturuldu"
            return f"Tabii, dosyayı oluşturuyorum. [ACTION: create_file | path={path} | content={content}]"

        # 2) Müzik/şarkı çal (uygulama aç'dan ÖNCE)
        if any(w in t for w in ["çal", "şarkı", "müzik", "sarki", "muzik", "music", "play"]):
            # uygulama adı geçiyorsa (spotify) ona bırak
            if not any(a in t for a in ["spotify", "chrome", "safari"]):
                import re as _re
                q = _re.sub(r"\b(elişa|eleşa|elisha|hey|çal|oynat|başlat|bir|şarkı|sarki|müzik|muzik|aç)\b", "", user_text, flags=_re.I).strip(" ,.")
                if len(q) < 3: q = "türkçe pop"
                return f"Hemen çalıyorum. [ACTION: play_music | query={q}]"

        # 3) Uygulama/site aç
        m = re.search(r"(youtube|github|twitter|x\.com|instagram|netflix|hürriyet|milliyet).{0,10}(aç|git)", t)
        if m:
            site = m.group(1)
            return f"Açılıyor. [ACTION: open_url | url={site}.com | name={site}]"
        m = re.search(r"(chrome|firefox|safari|vscode|code|finder|terminal|hesap makinesi|notepad|spotify|discord).{0,10}aç", t)
        if m or "uygulama aç" in t or "açar mısın" in t:
            app = "chrome"
            for cand in ["chrome", "firefox", "safari", "vscode", "code", "finder", "terminal", "spotify"]:
                if cand in t:
                    app = cand
                    break
            return f"Hemen açıyorum. [ACTION: open_app | app={app}]"

        # dosya listele
        if any(w in t for w in ["dosyaları listele", "klasörü göster", "dosyaları göster", "listele"]) and any(w in t for w in ["dosya", "klasör", "masaüstü", "desktop"]):
            # path belirle
            p = "~/Desktop"
            if "indirilenler" in t:
                p = "~/Downloads"
            elif "belgeler" in t:
                p = "~/Documents"
            return f"[ACTION: list_files | path={p}]"
        if "dosya oku" in t or "dosyayı oku" in t or "oku" in t and ".txt" in t:
            m = re.search(r"(\S+\.txt)", t)
            if m:
                return f"[ACTION: read_file | path=~/Desktop/{m.group(1)}]"

        # web arama
        if any(w in t for w in ["havadurumu", "hava durumu", "haber", "nedir", "kimdir", "hava nasıl"]) or ("ara" in t and len(t.split()) <= 6):
            q = user_text
            # sadece wake word'ü temizle, 'ara' kelimesini silme (Ankara bozuluyordu)
            q = re.sub(r"\b(elişa|eleşa|elisha|hey elişa|hey eleşa)\b", "", q, flags=re.I).strip(" ,")
            # baştaki 'ara' komutunu temizle: 'Ankara hava durumu ara' -> 'Ankara hava durumu'
            q = re.sub(r"^\s*ara\s+", "", q, flags=re.I)
            q = re.sub(r"\s*ara\s*$", "", q, flags=re.I)
            if not q:
                q = user_text
            return f"Arıyorum: {q} [ACTION: web_search | query={q}]"

        # sistem ses
        if "sesi aç" in t or "sesi yükselt" in t:
            return "[ACTION: system_volume | action=up]"
        if "sesi kıs" in t or "sessize al" in t:
            return "[ACTION: system_volume | action=down]"
        if "sessiz" in t:
            return "[ACTION: system_volume | action=mute]"

        # ekran görüntüsü
        if "ekran görüntüsü" in t or "screenshot" in t:
            return "[ACTION: screenshot]"

        # selamlar (eylem yoksa)
        if any(w in t for w in ["merhaba", "selam", "hey", "günaydın", "iyi akşam", "iyi günler"]):
            return "Merhaba! Ben ELİŞA, nasıl yardımcı olabilirim?"

        # saat/tarih
        if "saat kaç" in t or "tarih ne" in t:
            import datetime
            now = datetime.datetime.now().strftime("%H:%M, %d %B %Y")
            return f"Şu an saat {now}."

        # genel sohbet
        if len(t) < 3:
            return "Efendim? Seni dinliyorum."

        # fallback LLM yokken bile mantıklı cevap
        return f"Anladım: \"{user_text}\". Şu an offline mock moddayım — Ollama kurarsan (qwen2.5:3b) çok daha akıllı cevaplar verebilirim. Yine de sistem komutlarını çalıştırabilirim. Ne yapmamı istersin?"

    def clear_history(self):
        self.history = []
