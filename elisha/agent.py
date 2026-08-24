import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from .persona_agent import AGENT_PROMPT_TR
from .tools.registry import ToolRegistry
from .log import log, err
from .security import NeedConfirmation, PermissionManager


class AgentStep:
    def __init__(self, kind: str, name: str = "", detail: str = ""):
        self.kind = kind          # "llm" | "tool" | "final" | "limit"
        self.name = name
        self.detail = detail

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "detail": self.detail}


class AgentResult:
    def __init__(self, final_text: str, steps: List[AgentStep],
                 tool_calls: List[Dict[str, Any]], aborted: bool = False):
        self.final_text = final_text
        self.steps = steps
        self.tool_calls = tool_calls
        self.aborted = aborted


class AgentLoop:
    def __init__(self, config: dict, llm_host: str, llm_model: str,
                 registry: ToolRegistry,
                 on_status: Optional[Callable[[str], None]] = None,
                 permissions: Optional[PermissionManager] = None,
                 memory_store=None,
                 provider=None):
        self.config = config
        # Ollama fallback her zaman GERÇEK ollama modelini kullanmalı;
        # llm_model birincil sağlayıcının modeli olabilir (örn. Groq modeli)
        # → Ollama'ya "openai/gpt-oss-120b" sorulursa 404 döner!
        _llm_cfg = (config.get("llm", {}) or {})
        self.host = llm_host or _llm_cfg.get("host", "http://localhost:11434")
        self.model = _llm_cfg.get("model", "qwen2.5:7b")
        # Provider bir OLLAMA örneğiyse otomatik yükseltmesini takip et
        # (örn. qwen3:8b indirildiyse). Groq/Gemini modelleri ASLA Ollama'ya sorulmaz!
        if provider is not None and getattr(provider, "name", "") == "ollama":
            self.model = getattr(provider, "model_name", self.model)
        self.registry = registry
        self.on_status = on_status or (lambda s: None)
        self.permissions = permissions or PermissionManager(config)
        self.memory = memory_store
        self._provider = provider  # LLMProvider instance (Groq/Ollama/None)
        agent_cfg = config.get("agent", {}) or {}
        self.enabled = bool(agent_cfg.get("enabled", True))
        self.max_steps = int(agent_cfg.get("max_steps", 8))
        self.temperature = float((config.get("llm", {}) or {}).get("temperature", 0.5))
        self.max_tokens = int((config.get("llm", {}) or {}).get("max_tokens", 1500))
        self.system_prompt = ((config.get("llm", {}) or {}).get("agent_system_prompt")
                              or AGENT_PROMPT_TR)

    def _status(self, text: str):
        try:
            self.on_status(text)
        except Exception:
            pass

    # _live_context önbelleği: her mesajda subprocess çalıştırmamak için
    _LC_CACHE = {"batt": ("", 0.0), "app": ("", 0.0), "app_fail_until": 0.0}

    def _self_knowledge(self) -> str:
        """[KİMLİK] bloğu — ELİŞA'nın kendini ve yeteneklerini bilmesi.
        Araç seti statik olduğu için 300 sn önbelleklenir; model/sağlayıcı
        bilgisi her seferinde tazelenir."""
        import time as _t
        cache = getattr(self, "_self_cache", None)
        if cache and _t.time() - cache[0] < 300 and self._provider_signature() == cache[2]:
            return cache[1]

        # Aktif beyin
        brain = "yerel Ollama (qwen)"
        try:
            if self._provider is not None:
                pn = getattr(self._provider, "name", "?")
                pm = getattr(self._provider, "model_name", "")
                brain = f"{pn}/{pm}"
        except Exception:
            pass

        # Araçları kategorilere göre grupla (isimlerden)
        groups: Dict[str, list] = {}
        _CAT = {
            "dosya": ("list_files", "read_file", "create_file", "write_file",
                      "copy_file", "move_file", "delete_file", "search_files"),
            "uygulama": ("open_application", "close_application", "open_url"),
            "web": ("web_search", "fetch_webpage"),
            "medya": ("play_music", "set_volume", "take_screenshot"),
            "kişisel": ("set_reminder", "create_note", "remember", "recall",
                        "get_time", "get_date", "get_location", "get_system_info",
                        "get_weather", "list_reminders"),
        }
        names = self.registry.list_tools() if hasattr(self.registry, "list_tools") else []
        for n in names:
            for cat, members in _CAT.items():
                if n in members or any(m in n for m in members):
                    groups.setdefault(cat, []).append(n)
                    break
            else:
                groups.setdefault("diğer", []).append(n)

        cat_tr = {
            "dosya": "Dosyalar", "uygulama": "Uygulamalar/Web",
            "web": "İnternet", "medya": "Medya/Sistem",
            "kişisel": "Kişisel Yardım", "diğer": "Diğer",
        }
        lines = [f"[KİMLİK VE YETENEKLERİN] Adın ELİŞA. Kullanıcının Mac'inde "
                 f"yerel olarak çalışan Türkçe sesli asistansın."]
        lines.append(f"Beynin: {brain} · Kulakların: whisper STT · Sesin: Piper (Türkçe kadın)")
        parts = []
        for cat, ns in groups.items():
            parts.append(f"{cat_tr.get(cat, cat)}: {', '.join(sorted(ns))}")
        lines.append(f"Toplam {len(names)} aracın var → " + " | ".join(parts))
        try:
            if self.memory is not None:
                mc = self.memory.count_memories()
                if mc:
                    lines.append(f"Hafızanda kullanıcı hakkında {mc} kayıt var.")
        except Exception:
            pass
        lines.append('Kendinden bahsedilirse ("kendini tanıt", "ne yapabilirsin", '
                     '"seni kim yaptı") bu bilgiyi doğal bir dille anlat.')

        block = "\n".join(lines)
        self._self_cache = (_t.time(), block, self._provider_signature())
        return block

    def _provider_signature(self) -> str:
        return f"{getattr(self._provider, 'name', '?')}:{getattr(self._provider, 'model_name', '')}"

    @classmethod
    def _live_context(cls) -> str:
        """Anlık sistem bağlamı — Jarvis farkındalığı: saat, pil, öndeki uygulama.
        Pil 60 sn, öndeki uygulama 15 sn önbelleklenir; osascript sürekli
        hata verirse 5 dakika boyunca denenmez (maliyet kontrolü)."""
        import time as _t
        import datetime as _dt
        now = _dt.datetime.now()
        ctx = [f"[ANLIK BAĞLAM] Şu an: {now.strftime('%d.%m.%Y %H:%M')} "
               f"({['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'][now.weekday()]})"]
        cache = cls._LC_CACHE
        ts = _t.time()
        try:
            if not cache["batt"][1] or ts - cache["batt"][1] > 60:
                import subprocess as _sp
                r = _sp.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3)
                import re as _re
                m = _re.search(r'(\d+)%', r.stdout)
                val = ""
                if m:
                    ac = "şarjda" if "AC Power" in r.stdout else "pil"
                    val = f"Pil: %{m.group(1)} ({ac})"
                cache["batt"] = (val, ts)
            if cache["batt"][0]:
                ctx.append(cache["batt"][0])
        except Exception:
            pass
        try:
            if ts >= cache["app_fail_until"]:
                if not cache["app"][1] or ts - cache["app"][1] > 15:
                    import subprocess as _sp
                    r = _sp.run(["osascript", "-e",
                                 'tell application "System Events" to get name of first process whose frontmost is true'],
                                capture_output=True, text=True, timeout=3)
                    app = (r.stdout or "").strip()
                    if app:
                        cache["app"] = (f"Kullanıcının öndeki uygulaması: {app}", ts)
                    elif (r.returncode or 0) != 0:
                        cache["app_fail_until"] = ts + 300   # izin yok → 5 dk bekle
                        cache["app"] = ("", 0.0)
                    else:
                        cache["app"] = ("", ts)              # boş ama sorun değil
            if cache["app"][0]:
                ctx.append(cache["app"][0])
        except Exception:
            pass
        return "\n".join(ctx)

    def run(self, user_text: str, history: Optional[List[Dict[str, str]]] = None) -> AgentResult:
        tools = self.registry.to_ollama_tools()
        system_prompt = self.system_prompt
        try:
            live = self._live_context()
            if live:
                system_prompt = system_prompt + "\n\n" + live
        except Exception:
            pass
        try:
            ident = self._self_knowledge()
            if ident:
                system_prompt = system_prompt + "\n\n" + ident
        except Exception:
            pass
        if self.memory is not None:
            try:
                mem_block = self.memory.context_block()
                if mem_block:
                    system_prompt = system_prompt + "\n\n" + mem_block
            except Exception:
                pass
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        steps: List[AgentStep] = []
        executed: List[Dict[str, Any]] = []
        step_count = 0

        while True:
            step_count += 1
            if step_count > self.max_steps:
                self._status("🛑 Adım limitine ulaştım, özetliyorum.")
                summary = self._force_summary(messages)
                steps.append(AgentStep("limit", detail=f"{self.max_steps} adım aşıldı"))
                return AgentResult(summary, steps, executed, aborted=True)

            msg = self._chat(messages, tools)
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls and self._is_malformed(content):
                err(f"bozuk LLM çıktısı, tekrar deneniyor: {content[:80]}")
                msg = self._chat(messages, tools)
                content = (msg.get("content") or "").strip()
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls and self._is_malformed(content):
                    # İkinci deneme de bozuksa toplanan sonuçlarla temiz özet üret
                    content = self._force_summary(messages)

            if not tool_calls:
                final = content
                if not final:
                    # Sağlayıcılar meşgulse bile kullanıcıyı boş bırakma
                    if executed:
                        # Önce toplanan sonuçlardan düzgün cümle üretmeye çalış
                        summary = self._force_summary(messages)
                        if summary and not self._is_malformed(summary):
                            final = summary
                        else:
                            last_ok = next((e for e in reversed(executed)
                                            if e["success"]), None)
                            msg_txt = ((last_ok.get("result") or {}).get("message") or "") \
                                if last_ok else ""
                            final = ("Bulduklarım:\n" + msg_txt[:450]) if msg_txt \
                                else "İstediğini tamamladım ama özetleyemedim."
                    else:
                        final = ("Şu an model sağlayıcılarım biraz meşgul "
                                 "(Groq limiti doldu), kafamı toplayamadım. "
                                 "Tekrar söyler misin?")
                steps.append(AgentStep("final", detail=final[:200]))
                return AgentResult(final, steps, executed)

            messages.append({"role": "assistant",
                             "content": content,
                             "tool_calls": tool_calls})

            for call in tool_calls:
                fn = (call.get("function") or {})
                name = fn.get("name", "")
                tool_call_id = call.get("id", "")  # Groq/OpenAI tool_call_id
                raw_args = fn.get("arguments") or {}
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args or "{}")
                    except Exception:
                        raw_args = {}
                args = {k: v for k, v in (raw_args or {}).items() if v is not None}

                step_count += 1
                if step_count > self.max_steps:
                    result_text = "Adım limiti doldu, bu araç çalıştırılamadı."
                    steps.append(AgentStep("limit", name=name))
                    tool_msg = {"role": "tool", "content": result_text}
                    if tool_call_id:
                        tool_msg["tool_call_id"] = tool_call_id
                    messages.append(tool_msg)
                    continue

                self._status(self._status_label(name, args))

                # GÜVENLİK: HIGH/CRITICAL araçlar kullanıcı onayı ister
                if self.permissions.needs_confirmation(self.registry, name):
                    question = self.permissions.build_question(self.registry, name, args)
                    self.permissions.request(name, args, question)
                    raise NeedConfirmation(name, args, question)

                t0 = time.time()
                result = self.registry.execute(name, args)
                dt = time.time() - t0
                result_text = result.for_llm()
                steps.append(AgentStep("tool", name=name,
                                       detail=f"{result.success} ({dt:.2f}s): {result_text[:120]}"))
                executed.append({
                    "tool": name, "args": args,
                    "success": result.success,
                    "result": result.to_dict(),
                })
                log("TOOL", f"🔧 {name}({args}) -> {'OK' if result.success else 'FAIL'} "
                      f"[{dt:.2f}s] {result_text[:150]}")
                tool_msg = {"role": "tool", "content": result_text}
                if tool_call_id:
                    tool_msg["tool_call_id"] = tool_call_id
                messages.append(tool_msg)

    @staticmethod
    def _trim_messages(messages: List[Dict[str, Any]], max_chars: int = 110_000) -> List[Dict[str, Any]]:
        """Groq 413 (Payload Too Large) koruması:
        1) Tekil dev mesajları (uzun araç çıktıları) kırp
        2) Hâlâ büyüksse en eski geçmişi at (system prompt asla atılmaz)"""
        if not messages:
            return messages
        LIMIT_MSG = 8_000  # tek mesaj üst sınırı (araç çıktıları için)
        trimmed = []
        for m in messages:
            c = m.get("content")
            if isinstance(c, str) and len(c) > LIMIT_MSG:
                m = dict(m)
                m["content"] = c[:LIMIT_MSG] + "\n…[çıktı kısaltıldı]"
            trimmed.append(m)
        def _size(ms):
            return sum(len(str(m.get("content") or "")) for m in ms)
        if _size(trimmed) <= max_chars:
            return trimmed
        system = [trimmed[0]] if trimmed and trimmed[0].get("role") == "system" else []
        rest = trimmed[len(system):]
        while rest and _size(system + rest) > max_chars:
            rest = rest[1:]
        log("AGENT", f"✂️ geçmiş kırpıldı → {_size(system + rest)} kr (413 koruması)")
        return system + rest

    def _chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Provider varsa onu kullan (Groq/Ollama), yoksa eski Ollama yoluna düş
        if self._provider and self._provider.supports_tools:
            # Groq ücretsiz katmanı ~30KB üstü isteği 413 ile reddediyor.
            # Küçük istekler Groq'a gitsin (hızlı); Groq sınırı için önceden kırp.
            prov_name = str(getattr(self._provider, "name", "")).lower()
            msgs = self._trim_messages(
                messages, max_chars=(15_000 if prov_name.startswith("groq") else 110_000))
            # Boyut önceden hesapla: Groq'un 30KB sınırını aşacaksa hiç uğraşma,
            # doğrudan geniş bağlamlı OpenRouter'a git (boşa hata turu atma).
            import json as _json
            est = len(_json.dumps(msgs, default=str)) + len(_json.dumps(tools or [], default=str))
            if prov_name.startswith("groq") and est > 26_000:
                o = self._chat_openrouter_final(messages, tools)
                if o is not None:
                    return o
            try:
                response = self._provider.chat(
                    msgs, tools=tools,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                return {"content": response.content, "tool_calls": response.tool_calls or []}
            except Exception as e:
                # Sağlayıcı görsel/ikili içeriği reddederse fallback işe yaramaz,
                # anlamlı Türkçe mesaj döndür.
                _es = str(e).lower()
                if "image" in _es or "multimodal" in _es or "vision" in _es:
                    err(f"{self._provider.name} görsel içeriği reddetti: {e}")
                    return {"content": (
                        "Üzgünüm, görsel dosyaları şu an inceleyemiyorum; yalnızca metinle "
                        "çalışıyorum. İstersen ekran görüntüsünü masaüstüne kaydedebilirim ya da "
                        "içeriğini kendi sözlerinle aktarırsan yardımcı olabilirim."
                    ), "tool_calls": []}
                # Groq 429/500 → önce Gemini (tool'suz final üretici), sonra Ollama
                err(f"{self._provider.name} hatası: {e}, yedek sağlayıcılar deneniyor")
                o = self._chat_openrouter_final(msgs, tools)
                if o is not None:
                    return o
                g = self._chat_gemini_final(messages)
                if g is not None:
                    return g
                return self._chat_ollama_fallback(messages, tools)

        # Fallback: doğrudan Ollama HTTP (eski yol)
        return self._chat_ollama_fallback(messages, tools)

    def _chat_openrouter_final(self, messages: List[Dict[str, Any]],
                               tools: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        """Groq 413/429 verdiğinde ücretsiz OpenRouter'ı FINAL üretici olarak kullan.
        tools da geçirilir → model araç çağırmaya devam edebilir."""
        try:
            from .llm.providers import OpenRouterProvider, ProviderStatus
            op = OpenRouterProvider(self.config)
            if op.status() != ProviderStatus.AVAILABLE:
                return None
            resp = op.chat(messages, tools=tools,
                           temperature=self.temperature,
                           max_tokens=self.max_tokens)
            content = self._strip_think(getattr(resp, "content", "") or "").strip()
            if not content:
                return None
            log("AGENT", f"✅ OpenRouter yedeği devrede ({len(content)} kr)")
            return {"content": content, "tool_calls": []}
        except Exception as e:
            err(f"OpenRouter yedeği başarısız: {e}")
            return None

    def _chat_gemini_final(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Groq + Ollama ikisi de çöktüyse Gemini'yi tool'suz FINAL cevap
        üreticisi olarak kullan (araç sonuçlarını metne döker)."""
        try:
            from .llm.providers import GeminiProvider, ProviderStatus
            gp = GeminiProvider(self.config)
            if gp.status() != ProviderStatus.AVAILABLE:
                return None
            resp = gp.chat(messages, tools=None,
                           temperature=self.temperature,
                           max_tokens=self.max_tokens)
            content = (getattr(resp, "content", "") or "").strip()
            if not content:
                return None
            log("AGENT", f"✅ Gemini final yedeği devrede ({len(content)} kr)")
            return {"content": content, "tool_calls": []}
        except Exception as e:
            err(f"Gemini yedeği de başarısız: {e}")
            return None

    @staticmethod
    def _strip_think(text: str) -> str:
        """qwen/gpt-oss modellerinin <think> bloklarını ve boş artıkları temizle."""
        import re as _re
        t = _re.sub(r"<think>.*?</think>", "", text or "", flags=_re.DOTALL).strip()
        return t

    def _chat_ollama_fallback(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ollama'ya doğrudan HTTP isteği (fallback)."""
        # tool mesajlarındaki tool_call_id'yi temizle (Ollama anlamaz)
        clean_msgs = []
        for m in messages:
            cm = dict(m)
            cm.pop("tool_call_id", None)
            if "tool_calls" in cm:
                # Ollama formatı: id alanı yok
                cm["tool_calls"] = [
                    {"function": tc.get("function", tc)} for tc in cm["tool_calls"]
                ]
            clean_msgs.append(cm)
        # Son kullanıcı mesajına nihai-cevap disiplini ekle (qwen meta-konuşmasın)
        for i in range(len(clean_msgs) - 1, -1, -1):
            if clean_msgs[i].get("role") == "user":
                c = str(clean_msgs[i].get("content") or "")
                clean_msgs[i]["content"] = (
                    c + "\n\n(Sadece nihai cevabı ver — süreç anlatma, "
                       "geri soru sorma, araçtan bahsetme.)")
                break
        payload = {
            "model": self.model,
            "messages": clean_msgs,
            "stream": False,
            "tools": tools,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        try:
            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=90)
            r.raise_for_status()
            message = r.json().get("message", {})
            content = self._strip_think(message.get("content") or "")
            tool_calls = message.get("tool_calls") or []
            if content or tool_calls:
                return {"content": content, "tool_calls": tool_calls}
            # Boş yanıt (qwen bazen tools payload'unda takılıyor) → toolsuz tekrar dene
            err("Ollama boş yanıt verdi → toolsuz tekrar deneniyor")
            payload.pop("tools", None)
            payload["messages"] = [m for m in clean_msgs if m.get("role") != "tool"] + [
                {"role": "user",
                 "content": "Yukarıdaki araç sonuçlarını KISA ve doğal bir Türkçe cümleyle özetle. Araç çağırma."}
            ]
            r2 = requests.post(f"{self.host}/api/chat", json=payload, timeout=90)
            r2.raise_for_status()
            content2 = self._strip_think((r2.json().get("message") or {}).get("content") or "")
            if content2:
                return {"content": content2, "tool_calls": []}
            return {"content": (
                "Şu an hem bulut modellerim sınıra takıldı hem yerel model boş döndü. "
                "Biraz sonra tekrar dener misin?"
            ), "tool_calls": []}
        except Exception as e:
            err(f"Ollama fallback de başarısız: {e}")
            return {"content": "Üzgünüm, şu an hem Groq hem Ollama yanıt veremiyor. Biraz sonra tekrar dener misin?", "tool_calls": []}

    def _force_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Adım limiti aşıldığında toplanan sonuçlarla NAHAİ cevap üret.
        Önce aktif provider (Groq vb.) — eski Ollama yolu yalnızca yedek."""
        msgs = [m for m in messages]
        msgs.append({"role": "user",
                     "content": "Adım limitine ulaştık. Şu ana kadar elde ettiğin sonuçlarla "
                                "kullanıcıya DOĞRUDAN nihai cevabı ver. Süreci anlatma, yeni araç "
                                "çağırma, geri soru sorma. Sadece cevap:"})
        # 1) Aktif provider ile (Groq/OpenRouter/…) — doğru format, hızlı
        if getattr(self, "_provider", None) and self._provider.status().value == "available":
            try:
                resp = self._provider.chat(msgs, tools=None,
                                           temperature=0.3, max_tokens=300)
                txt = self._strip_think(getattr(resp, "content", "") or "").strip()
                if txt:
                    return txt
            except Exception as e:
                err(f"özet (provider) hatası: {e}")
        # 2) Eski Ollama yolu (yerel son çare)
        try:
            payload = {
                "model": self.model,
                "messages": msgs,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 200},
            }
            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=60)
            r.raise_for_status()
            return self._strip_think(
                r.json().get("message", {}).get("content") or "").strip() or \
                   "Birkaç adım çalıştırdım ama sonucu özetleyemedim."
        except Exception as e:
            return f"Görev yarıda kaldı: {e}"

    @staticmethod
    def _is_malformed(content: str) -> bool:
        if not content or len(content.strip()) < 2:
            return True
        if re.search(r"\[(Çalıştır|çalıştır|ACTION|action|tool|araç)", content):
            return True
        if re.search(r"\[ACTION:[^\]]*\]", content):
            return True
        # Modelin araç çağrısını METİN olarak dökmesi: '{"tool": ...}' / '{"name": ...}'
        s = content.strip()
        if s.startswith("{") and re.search(
                r'"(tool|tools|function|name|args|arguments)"\s*:', s):
            return True
        return False

    @staticmethod
    def _status_label(tool_name: str, args: Dict[str, Any]) -> str:
        labels = {
            "web_search": "🔍 İnternette arıyorum...",
            "fetch_webpage": "🌐 Sayfayı okuyorum...",
            "list_files": "📁 Dosyaları inceliyorum...",
            "read_file": "📄 Dosyayı okuyorum...",
            "create_file": "📝 Dosya oluşturuyorum...",
            "write_file": "✏️ Dosyaya yazıyorum...",
            "copy_file": "📋 Dosyayı kopyalıyorum...",
            "move_file": "📦 Dosyayı taşıyorum...",
            "delete_file": "🗑️ Dosyayı siliyorum...",
            "open_application": f"🚀 {args.get('app', 'uygulamayı')} açıyorum...",
            "close_application": f"🔒 {args.get('app', 'uygulamayı')} kapatıyorum...",
            "open_url": "🌐 Siteyi açıyorum...",
            "play_music": "🎵 Müziği başlatıyorum...",
            "set_volume": "🔊 Ses ayarlıyorum...",
            "take_screenshot": "📸 Ekran görüntüsü alıyorum...",
            "get_time": "🕐 Saate bakıyorum...",
            "get_date": "📅 Tarihe bakıyorum...",
            "get_system_info": "💻 Sistem bilgisine bakıyorum...",
        }
        return labels.get(tool_name, f"⚙️ {tool_name} çalıştırıyorum...")
