import re
from typing import Optional

from .tools.registry import ToolRegistry
from .security import NeedConfirmation, PermissionManager


class FastPath:
    """Yaygın komutları deterministik olarak yönlendirir (LLM'e gitmeden).

    Küçük lokal modellerde (qwen2.5:1.5b) native tool calling güvenilir değil.
    Bu yüzden net komutlar doğrudan araçlara bağlanır: hızlı (<0.1s), %100 güvenilir,
    Ollama kapalıyken bile çalışır. Karmaşık/çok adımlı istekler agent loop'a düşer.

    GÜVENLİK: HIGH/CRITICAL riskli araçlar (ör. delete_file) PermissionManager'dan
    geçer — onay istenmezse NeedConfirmation fırlatır, orchestrator onay akışına alır.
    """

    def __init__(self, config: dict, registry: ToolRegistry, memory_store=None,
                 on_status=None, permissions: PermissionManager = None):
        self.config = config
        self.registry = registry
        self.memory = memory_store
        self.on_status = on_status or (lambda s: None)
        self.permissions = permissions

    def _run(self, tool: str, args: dict, label: str = ""):
        try:
            self.on_status(label or f"⚙️ {tool} çalıştırıyorum...")
        except Exception:
            pass
        if self.permissions is not None and \
           self.permissions.needs_confirmation(self.registry, tool):
            question = self.permissions.build_question(self.registry, tool, args)
            self.permissions.request(tool, args, question)  # pending'e kaydet!
            raise NeedConfirmation(tool, args, question)
        return self.registry.execute(tool, args)

    def try_route(self, text: str) -> Optional[str]:
        t = text.lower().strip()
        if not t:
            return None

        # --- kimlik soruları (LLM'e gitmeden tutarlı cevap) ---
        _kimlik = re.search(
            r"\b(kimsin|kim(dir)?sin|adın ne|ismin ne|seni kim (yaptı|oluşturdu|programladı|geliştirdi|kurdu)|kim (yaptı|kurdu|geliştirdi) seni|nasıl (yapıldın|oluşturuldun))\b",
            t
        )
        if _kimlik:
            return "Ben ELİŞA — sana yardımcı olmak için yapılmış Türkçe bir sesli asistanım. Bir yazılımcı tarafından tamamen yerel olarak çalışacak şekilde geliştirildi."

        # --- ne yapabilirsin ---
        if re.search(r"\b(ne yapabilir?sin|neler yapabilir?sin|yeteneklerin|yardım edebilir misin)\b", t):
            return ("Saat/tarih söylerim, dosya açar/oluştururum, uygulama başlatırım, "
                    "müzik çalarım, internette araştırma yaparım, ve seninle sohbet ederim!")

        # --- dosya oluştur (müzik/uygulama kurallarından ÖNCE) ---
        if self._is_create_file(t):
            return self._create_file(t)

        # --- hafıza: hatırla / unut ---
        if re.search(r"\b(hatırla|hatirla|aklında tut|aklinda tut|ezberle)\b", t):
            return self._remember(text)
        if re.search(r"\bunut\b", t):
            return self._forget(text)

        # --- dosya silme (HIGH risk -> _run onay sistemine düşürür) ---
        if re.search(r"\b(sil|kaldır|kaldir|siliver)\b", t):
            m = re.search(
                r"([\w\-À-ÿ ]*[\w\-À-ÿ]+\.(?:txt|md|pdf|docx?|xlsx?|pptx?|csv|png|jpe?g|gif|heic|mp3|mp4|mov|zip))",
                text, re.I)
            if m:
                fname = m.group(1).strip()
                fname = re.sub(r"^(masaustundeki|masaustunde|masaustu|desktop|indirilenlerdeki|"
                               r"indirilenlerde|indirilenler|belgelerdeki|belgelerde|belgeler)\s+",
                               "", fname, flags=re.I).strip()
                r = self._run("delete_file", {"path": fname}, f"🗑️ {fname} siliniyor...")
                return r.message if r.success else f"Silmedim: {r.error}"

        # --- müzik/şarkı (uygulama açmadan önce) ---
        # DÜZELTME: "şarkı" veya "müzik" tek başına yeterli değil,
        # mutlaka bir fiil eşliğinde olmalı ("çal", "oynat", "dinle" gibi)
        _MUSIC_NOUNS = {"şarkı", "sarki", "müzik", "muzik", "music"}
        _MUSIC_VERBS = {"çal", "oynat", "dinle", "aç", "başlat"}
        _has_noun = any(w in t for w in _MUSIC_NOUNS)
        _has_verb = any(w in t for w in _MUSIC_VERBS)
        # Sadece spotify/chrome/safari yoksa ve hem fiil hem isim varsa
        if _has_noun and _has_verb and not any(a in t for a in ["spotify uygulaması", "chrome", "safari", "ses seviyesi"]):
            return self._music(text)
        # "çal [şarkı adı]" veya "oynat [şarkı]" — kısa form, isim olmasa bile
        if re.search(r"^(çal|oynat)\s+\w", t) and not any(a in t for a in ["chrome", "safari"]):
            return self._music(text)

        # --- bilinen site/url aç ---
        m = re.search(r"(youtube|github|twitter|x\.com|instagram|netflix|hürriyet|milliyet)", t)
        if m and re.search(r"(aç|açar|git|göster)", t):
            site = m.group(1).replace(".com", "")
            names = {"youtube": "YouTube", "github": "GitHub", "twitter": "Twitter",
                     "x.com": "X", "instagram": "Instagram", "netflix": "Netflix",
                     "hürriyet": "Hürriyet", "milliyet": "Milliyet"}
            name = names.get(m.group(1), site)
            r = self._run("open_url", {"url": f"{site}.com", "name": name}, f"🌐 {name} açıyorum...")
            return f"{name} açılıyor." if r.success else f"Siteyi açamadım: {r.error}"

        # --- uygulama aç / kapat ---
        m_open = re.search(r"\b(chrome|safari|firefox|vscode|code|finder|terminal|spotify|notes|notlar|calculator|hesap makinesi|mail|postacı)\b.{0,15}\b(aç|başlat|getir|açsan|açar)", t)
        if m_open or ("uygulama aç" in t or "açar mısın" in t):
            app = m_open.group(1) if m_open else ""
            aliases = {"notlar": "notes", "hesap makinesi": "calculator",
                       "postacı": "mail", "code": "vscode"}
            app = aliases.get(app, app or "finder")
            r = self._run("open_application", {"app": app}, f"🚀 {app} açıyorum...")
            return r.message if r.success else f"Açamadım: {r.error}"

        m_close = re.search(r"\b(chrome|safari|firefox|vscode|code|finder|terminal|spotify|notes|calculator|mail)\b.{0,10}\b(kapat|kessan|kapatır)", t)
        if m_close or re.search(r"\b(\w+)\b.{0,5}uygulamasını kapat", t):
            app = m_close.group(1) if m_close else re.search(r"\b(\w+)\b.{0,5}uygulamasını kapat", t).group(1)
            r = self._run("close_application", {"app": app}, f"🔒 {app} kapatıyorum...")
            return r.message if r.success else f"Kapatamadım: {r.error}"

        # --- ses seviyesi ---
        if re.search(r"ses(i)?\s*(biraz\s*)?(aç|yükselt|arttır|yukarı)", t):
            r = self._run("set_volume", {"action": "up"}, "🔊 Sesi yükseltiyorum...")
            return "Sesi yükselttim." if r.success else "Sesi değiştiremedim."
        if re.search(r"ses(i)?\s*(biraz\s*)?(kıs|azalt|aşağı|düşür)", t) or "sesi kıs" in t:
            r = self._run("set_volume", {"action": "down"}, "🔉 Sesi kısuyorum...")
            return "Sesi kıstım." if r.success else "Sesi değiştiremedim."
        if "sessize al" in t or "sessiz mod" in t or t.strip() == "sessiz":
            r = self._run("set_volume", {"action": "mute"}, "🔇 Sessize alıyorum...")
            return "Sessize aldım." if r.success else "Sessiz alamadım."
        if "sesi geri aç" in t or "sesi geri getir" in t:
            r = self._run("set_volume", {"action": "unmute"}, "🔊 Sesi geri açıyorum...")
            return "Sesi geri açtım." if r.success else "Yapamadım."

        # --- ekran görüntüsü ---
        if "ekran görüntüsü" in t or "ekran resmi" in t or "screenshot" in t:
            r = self._run("take_screenshot", {}, "📸 Ekran görüntüsü alıyorum...")
            return r.message if r.success else f"Ekran görüntüsü alamadım: {r.error}"

        # --- saat / tarih --- (sadece doğrudan sorgular, sohbet cümleleri değil)
        if re.search(r"\bsaat(ki|ı)?\b.{0,12}\b(kaç|kac|söyle|öğren)\b|saat kaç", t) and "zaman" not in t:
            r = self._run("get_time", {}, "🕐 Saate bakıyorum...")
            return r.message if r.success else "Saati öğrenemedim."
        # Tarih: sadece "tarih" veya "bugün ne gün" / "günlerden" gibi net tarih soruları
        if re.search(r"\b(tarih|günlerden|hangi gün|ayın kaç[iı]?|ne gün(dür)?)\b", t) or \
           re.search(r"\bbugün\b.{0,10}\b(kaç[iı]?|ne gün|hangi|tarih)\b", t):
            r = self._run("get_date", {}, "📅 Tarihe bakıyorum...")
            return r.message if r.success else "Tarihi öğrenemedim."

        # --- dosya listeleme ---
        if re.search(r"(listele|göster|neler var|kaç (dosya|öğe|klasör))", t) and \
           any(w in t for w in ["dosya", "klasör", "masaüstü", "desktop", "indirilenler", "downloads", "belgeler", "documents"]):
            p = "~/Desktop"
            if any(w in t for w in ["indirilenler", "download"]):
                p = "~/Downloads"
            elif any(w in t for w in ["belgeler", "documents", "doküman"]):
                p = "~/Documents"
            r = self._run("list_files", {"path": p}, "📁 Dosyaları listeliyorum...")
            return r.message if r.success else f"Listeleyemedim: {r.error}"

        # --- web arama (en sonda: site/müzik/uygulama kurallarına çarpmasın) ---
        # NOT: "nedir"/"kimdir" gibi bilgi soruları agent'a bırakılıyor (LLM cevaplar/arar)
        if any(w in t for w in ["hava durumu", "havadurumu", "hava nasıl", "haber",
                                "kaç para", "döviz", "borsa"]) or \
           (re.search(r"\bara\b", t) and len(t.split()) <= 7 and "şarkı" not in t):
            q = re.sub(r"\b(elişa|eleşa|elisha|hey)\b", "", text, flags=re.I).strip(" ,.")
            q = re.sub(r"^\s*(internette|google'da|googleda|webde)\s+", "", q, flags=re.I)
            q = re.sub(r"^\s*ara\s+", "", q, flags=re.I)
            q = re.sub(r"\s*ara(r)?( m[ıi]sın)?\s*$", "", q, flags=re.I).strip()
            if not q:
                q = text
            r = self._run("web_search", {"query": q}, "🔍 İnternette arıyorum...")
            return r.message if r.success else f"Aramayı yapamadım: {r.error}"

        return None

    def _is_create_file(self, t: str) -> bool:
        if any(w in t for w in ["dosya oluştur", "not oluştur", "dosya yap", "not al", "txt oluştur"]):
            return True
        if "oluştur" in t and any(x in t for x in [".txt", ".md", "not", "dosya"]):
            return True
        return False

    def _create_file(self, t: str) -> str:
        m_path = re.search(r"([\w\-À-ÿ]+\.(?:txt|md))", t)
        path = "~/Desktop/elisha-not.txt"
        if m_path:
            fname = m_path.group(1)
            path = fname if "/" in fname else f"~/Desktop/{fname}"
        m_content = re.search(r"içeriği?\s*[\"']?(.+?)[\"']?\s*(?:olsun)?$", t)
        content = "ELİŞA tarafından oluşturuldu"
        if m_content and len(m_content.group(1).strip()) > 2:
            content = m_content.group(1).strip()[:200]
        r = self._run("create_file", {"path": path, "content": content}, "📝 Dosya oluşturuyorum...")
        return r.message if r.success else f"Dosya oluşturamadım: {r.error}"

    def _music(self, original: str) -> str:
        q = re.sub(r"\b(elişa|eleşa|elisha|hey|çal|oynat|başlat|bir|şarkı|sarki|"
                   r"müzik|muzik|aç|lütfen|dinle|bana|bence|güzel|en iyi|iyi)\b",
                   "", original, flags=re.I).strip(" ,.?!")
        if len(q) < 2:
            q = "türkçe pop hit 2024"
        r = self._run("play_music", {"query": q}, "🎵 Müziği başlatıyorum...")
        return r.message if r.success else f"Müziği başlatamadım: {r.error}"

    # ---------- hafıza ----------

    def _remember(self, original: str) -> str:
        if self.memory is None:
            return "Hafıza şu an kapalı."
        value = re.sub(
            r"\b(elişa|eleşa|elisha|hey|bunu|şunu|sunu|onu|lütfen|lutfen|hatırla|hatirla|"
            r"aklında tut|aklinda tut|ezberle|kaydet)\b",
            "", original, flags=re.I).strip(" ,.!?")
        if len(value) < 3:
            value = original
        words = [w for w in re.split(r"\W+", value.lower()) if len(w) > 2][:4]
        key = "_".join(words) or f"not_{int(__import__('time').time())}"
        category = "genel"
        v = value.lower()
        if any(w in v for w in ["geliştir", "gelistir", "proje", "yazılım", "yazilim", "kod", "çalışıyorum", "calisiyorum"]):
            category = "proje"
        elif any(w in v for w in ["adım", "adim", "ismim", "benim ad"]):
            category = "kisi"
        elif any(w in v for w in ["seviyorum", "tercih", "tercih", "hoşuma", "hosuma"]):
            category = "tercih"
        importance = 2.0 if "önemli" in v or "onemli" in v else 1.0
        ok = self.memory.remember(key, value, category, importance)
        return "Tamam, bunu akılda tutacağım." if ok else "Bunu kaydedemedim."

    def _forget(self, original: str) -> str:
        if self.memory is None:
            return "Hafıza şu an kapalı."
        q = re.sub(r"\b(elişa|eleşa|elisha|hey|bunu|şunu|onu|lütfen|unut|unuttum|artık|artik|tamam)\b",
                   "", original, flags=re.I).strip(" ,.!?")
        n = self.memory.forget(q)
        if n > 0:
            return "Tamam, artık onu unuttum."
        return "Böyle bir kayıt bulamadım zaten."
