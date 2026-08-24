"""
ELİŞA LLM Provider Abstraction
===============================
Desteklenen sağlayıcılar:
  - OllamaProvider  (yerel, tool calling destekli)
  - GroqProvider    (bulut, ücretsiz katman, tool calling destekli, çok hızlı)
  - GeminiProvider  (bulut, ücretsiz katman, sadece sohbet)

API anahtarları:
  GROQ_API_KEY   → console.groq.com'dan al
  GEMINI_API_KEY → aistudio.google.com'dan al
  Asla kaynak koda veya config.yaml'a yazılmaz.
"""

import os
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import requests


class ProviderStatus(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass
class ChatResponse:
    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    latency_ms: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMProvider(ABC):
    """Tüm LLM sağlayıcıları için temel sınıf."""

    name: str = "base"
    model_name: str = ""
    supports_tools: bool = False

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Sağlayıcının erişilebilirliğini kontrol et."""
        ...

    @abstractmethod
    def chat(self, messages: List[Dict[str, Any]],
             tools: Optional[List[Dict[str, Any]]] = None,
             **opts) -> ChatResponse:
        """Mesaj listesiyle sohbet et, opsiyonel tool tanımlarıyla."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# OLLAMA PROVIDER (Yerel)
# ═══════════════════════════════════════════════════════════════════════════════

class OllamaProvider(LLMProvider):
    name = "ollama"
    supports_tools = True

    def __init__(self, config: dict):
        cfg = config.get("llm", {}) or {}
        self.host = cfg.get("host", "http://localhost:11434")
        self.model_name = cfg.get("model", "qwen2.5:7b")
        self.fallback_model = cfg.get("fallback_model", "qwen2.5:1.5b")
        self._select_model()

    def _select_model(self):
        """Mevcut en iyi modeli seç."""
        # Yükseltme tercihi: qwen3:8b indirildiyse eski qwen2.5'ten otomatik öncelikli
        # (2026 benchmark: Qwen3 7/8B sınıfının en iyi çok dilli + tool-calling modeli)
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            available = [m["name"] for m in r.json().get("models", [])]
            if (self.model_name.startswith("qwen2.5")
                    and any(a.startswith("qwen3:8b") for a in available)):
                print("  ⬆️ Ollama: qwen3:8b bulundu → otomatik yükseltildi")
                self.model_name = "qwen3:8b"
            if self.model_name not in available:
                if self.fallback_model in available:
                    self.model_name = self.fallback_model
                elif available:
                    self.model_name = available[0]
        except Exception:
            pass

    def status(self) -> ProviderStatus:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=2)
            return ProviderStatus.AVAILABLE if r.status_code == 200 else ProviderStatus.ERROR
        except Exception:
            return ProviderStatus.UNAVAILABLE

    def chat(self, messages: List[Dict[str, Any]],
             tools: Optional[List[Dict[str, Any]]] = None,
             **opts) -> ChatResponse:
        import time
        t0 = time.time()

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": opts.get("temperature", 0.5),
                "num_predict": opts.get("max_tokens", 1500),
            },
        }
        if tools:
            payload["tools"] = tools

        r = requests.post(f"{self.host}/api/chat", json=payload, timeout=90)
        r.raise_for_status()
        msg = r.json().get("message", {})

        return ChatResponse(
            content=(msg.get("content") or "").strip(),
            tool_calls=msg.get("tool_calls") or [],
            provider=self.name,
            model=self.model_name,
            latency_ms=int((time.time() - t0) * 1000),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# GROQ PROVIDER (Bulut — ücretsiz, çok hızlı, tool calling destekli)
# ═══════════════════════════════════════════════════════════════════════════════

class GroqProvider(LLMProvider):
    """
    Groq: LPU donanımlı, 500+ token/s hız.
    Ücretsiz katman: rate limit var ama kişisel asistan trafiği için yeterli.
    API: OpenAI-uyumlu format.
    Key: GROQ_API_KEY env variable'dan okunur.
    """
    name = "groq"
    supports_tools = True
    API_URL = "https://api.groq.com/openai/v1/chat/completions"
    # Devre kesici: 429 fırtınasında boşa deneme yapma (tüm örnekler paylaşır)
    _cooldown_until = 0.0

    def __init__(self, config: dict):
        cfg = config.get("llm", {}) or {}
        self.model_name = cfg.get("groq_model", "openai/gpt-oss-120b")
        self.api_key = os.environ.get("GROQ_API_KEY", "")

    def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.AVAILABLE

    def chat(self, messages: List[Dict[str, Any]],
             tools: Optional[List[Dict[str, Any]]] = None,
             **opts) -> ChatResponse:
        import time
        t0 = time.time()

        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY tanımlı değil")
        # Soğuma penceresindeyse hemen pes et → Gemini/Ollama zinciri hızlı devreye girer
        now = time.time()
        if now < type(self)._cooldown_until:
            raise RuntimeError(
                f"{type(self).name} cooldown aktif ({type(self)._cooldown_until - now:.0f} sn kaldı)")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Ollama tool format → OpenAI format dönüşümü
        oai_tools = None
        if tools:
            oai_tools = []
            for t in tools:
                fn = t.get("function", t)
                oai_tools.append({
                    "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {}),
                    }
                })

        # Mesajları OpenAI API formatına normalize et
        oai_messages = self._normalize_messages(messages)

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": oai_messages,
            "temperature": opts.get("temperature", 0.5),
            "max_tokens": opts.get("max_tokens", 1500),
        }
        if oai_tools:
            payload["tools"] = oai_tools
            payload["tool_choice"] = "auto"

        r = requests.post(self.API_URL, headers=headers, json=payload, timeout=30)

        # Rate limit: kısa bekle ve tekrar dene
        if r.status_code == 429:
            retry_after = int(r.headers.get("retry-after", "3"))
            time.sleep(min(retry_after, 5))
            r = requests.post(self.API_URL, headers=headers, json=payload, timeout=30)
            if r.status_code == 429:
                # İkinci 429 → 60 sn soğuma: bu dakika limiti doldu,
                # her istekte boşa beklemek yerine yedek sağlayıcıya bırak.
                type(self)._cooldown_until = time.time() + 60.0
                print("  ⏳ groq rate limit — 60 sn cooldown (Gemini/Ollama devrede)")

        r.raise_for_status()
        type(self)._cooldown_until = 0.0   # başarılı → soğuma sıfırla
        data = r.json()

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = (msg.get("content") or "").strip()

        # <think>...</think> tag'lerini temizle (Qwen reasoning mode)
        import re as _re
        content = _re.sub(r'<think>.*?</think>', '', content, flags=_re.DOTALL).strip()

        # OpenAI tool_calls → Ollama format'a normalize et
        tool_calls = []
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            tool_calls.append({
                "id": tc.get("id", ""),  # tool_call_id'yi koru (Groq yanıt eşleştirmesi için)
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": args,
                }
            })

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.name,
            model=self.model_name,
            latency_ms=int((time.time() - t0) * 1000),
        )

    @staticmethod
    def _normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Mesajları OpenAI/Groq API formatına dönüştür.
        
        - assistant tool_calls: type + arguments string olmalı
        - tool mesajları: tool_call_id zorunlu
        """
        normalized = []
        for msg in messages:
            role = msg.get("role", "user")

            if role == "assistant" and msg.get("tool_calls"):
                # tool_calls'ı OpenAI formatına çevir
                oai_tool_calls = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    # arguments string olmalı
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    oai_tool_calls.append({
                        "id": tc.get("id", f"call_{len(oai_tool_calls)}"),
                        "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": args,
                        }
                    })
                normalized.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": oai_tool_calls,
                })
            elif role == "tool":
                normalized.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", "call_0"),
                    "content": msg.get("content", ""),
                })
            else:
                # system, user, normal assistant — olduğu gibi geç
                normalized.append({
                    "role": role,
                    "content": msg.get("content", ""),
                })
        return normalized


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# ÜCRETSİZ BULUT ZİNCİRİ (Groq yedekleri — hepsi OpenAI-uyumlu, kart gerekmez)
#   Cerebras    : aynı gpt-oss-120b, ultra hızlı, 30 RPM / 1M token/gün
#   NVIDIA NIM  : 100+ model, ~40 RPM (build.nvidia.com)
#   OpenRouter  : tek key → ~35 ücretsiz model (openrouter.ai)
# Key'ler secrets.env'e yazılınca OTOMATIK algılanır; yoksa zincir atlanır.
# ═══════════════════════════════════════════════════════════════════════════════

class CerebrasProvider(GroqProvider):
    """Cerebras: wafer-scale çip, gpt-oss-120b ücretsiz (30 RPM).
    Groq ile AYNI model → persona tutarlılığı korunur."""
    name = "cerebras"
    API_URL = "https://api.cerebras.ai/v1/chat/completions"

    def __init__(self, config: dict):
        cfg = config.get("llm", {}) or {}
        self.model_name = os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b")
        self.api_key = os.environ.get("CEREBRAS_API_KEY", "")


class NvidiaProvider(GroqProvider):
    """NVIDIA NIM: integrate.api.nvidia.com, ücretsiz katman (~40 RPM).
    Varsayılan: DeepSeek V4 Flash (güçlü akıl yürütme + tool calling)."""
    name = "nvidia"
    API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

    def __init__(self, config: dict):
        self.model_name = os.environ.get(
            "NVIDIA_MODEL", "deepseek-ai/deepseek-v4-flash")
        self.api_key = os.environ.get("NVIDIA_API_KEY", "")


class OpenRouterProvider(GroqProvider):
    """OpenRouter: tek key ile onlarca ':free' model.
    Model belirtilmezse ilk ücretsiz model otomatik seçilir."""
    name = "openrouter"
    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    # Groq'un sınıf-seviyesi cooldown'unu GÖLGELE — Groq 429'a düşse bile
    # OpenRouter yedeği bloke olmasın (ayrı sayaç).
    _cooldown_until = 0.0

    def __init__(self, config: dict):
        self.model_name = os.environ.get("OPENROUTER_MODEL", "")
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.model_name:
            self._pick_free_model()

    def _pick_free_model(self):
        # Hız ölçümü (Ağu 2026): super 1.5s, ultra 18s — hız önce gelir
        try:
            r = requests.get("https://openrouter.ai/api/v1/models", timeout=8,
                             headers={"User-Agent": "elisha/4.0"})
            free_ids = [m.get("id", "") for m in r.json().get("data", [])
                        if m.get("id", "").endswith(":free")]
            for pref in ("nemotron-3-super", "glm-5", "nemotron-3-ultra",
                         "gemma-4-31b", "deepseek", "llama"):
                hit = next((i for i in free_ids if pref in i), None)
                if hit:
                    self.model_name = hit
                    break
            if not self.model_name and free_ids:
                self.model_name = free_ids[0]
        except Exception:
            pass
        if not self.model_name:
            raise RuntimeError("OpenRouter ücretsiz model bulunamadı")

    def chat(self, messages, tools=None, **opts):
        # OpenRouter HTTP-Referer/X-Title header'ı ister (öneri)
        return super().chat(messages, tools, **opts)

    # ── GÖRÜ (vision) — Mark-XXXIX-OR'dan uyarlanan model havuzu deseni ──
    VISION_MODELS = [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
    ]
    _vision_rate_limited = {}  # model → cooldown bitiş zamanı
    _vision_pool_discovered = False

    def _vision_pool(self):
        """Havuz: statik tercih + canlı listeden görüntü destekleyen :free modeller."""
        pool = list(self.VISION_MODELS)
        if not self._vision_pool_discovered:
            try:
                r = requests.get("https://openrouter.ai/api/v1/models", timeout=8,
                                 headers={"User-Agent": "elisha/4.0"})
                for m in r.json().get("data", []):
                    mid = m.get("id", "")
                    if not mid.endswith(":free") or mid in pool:
                        continue
                    arch = (m.get("architecture") or {})
                    mod_in = arch.get("input_modalities") or arch.get("modality") or ""
                    if "image" in str(mod_in):
                        pool.append(mid)
                self._vision_pool_discovered = True
            except Exception:
                pass
        return pool

    def vision(self, prompt: str, image_b64: str, mime: str = "image/png",
               system: str = "Görüntüyü analiz et ve net, kısa Türkçe cümlelerle anlat.",
               max_tokens: int = 700) -> str:
        """Görüntü + soru → ücretsiz vision model havuzundan yanıt.
        Sırayla dener; 429 alan modeli 60 sn soğutur."""
        import time as _t
        now = _t.time()
        pool = [m for m in self._vision_pool()
                if self._vision_rate_limited.get(m, 0) < now]
        if not pool:
            pool = self.VISION_MODELS  # hepsi soğukta → tercih sırasıyla tekrar dene
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ]},
        ]
        last_err = "bilinmeyen"
        for model in pool:
            payload = {"model": model, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.2}
            try:
                r = requests.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json",
                             "HTTP-Referer": "https://github.com/elisha",
                             "X-Title": "ELISHA"},
                    json=payload, timeout=45)
                if r.status_code == 429:
                    self._vision_rate_limited[model] = _t.time() + 60
                    last_err = f"{model}: 429"
                    continue
                if r.status_code != 200:
                    last_err = f"{model}: HTTP {r.status_code} {r.text[:120]}"
                    continue
                content = (r.json().get("choices", [{}])[0]
                           .get("message", {}).get("content") or "").strip()
                if content:
                    return content
                last_err = f"{model}: boş yanıt"
            except Exception as e:
                last_err = f"{model}: {e}"
        raise RuntimeError(f"Vision havuzu başarısız — {last_err}")

# GEMINI PROVIDER (Bulut — ücretsiz, iyi Türkçe, sadece sohbet)

class GeminiProvider(LLMProvider):
    # Yedek zincirin hızlı dönmesi için kısa timeout (ana beyin Groq zaten)
    NET_TIMEOUT = 15
    """
    Google Gemini: Ücretsiz katman (1500 istek/gün).
    Türkçe'de güçlü (Google'ın çok dilli veri derinliği).
    Tool calling desteklenmiyor (sohbet modu).
    Key: GEMINI_API_KEY env variable'dan okunur.
    """
    name = "gemini"
    supports_tools = False
    API_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, config: dict):
        cfg = config.get("llm", {}) or {}
        self.model_name = cfg.get("gemini_model", "gemini-flash-latest")
        self.api_key = os.environ.get("GEMINI_API_KEY", "")

    def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.AVAILABLE

    def chat(self, messages: List[Dict[str, Any]],
             tools: Optional[List[Dict[str, Any]]] = None,
             **opts) -> ChatResponse:
        import time
        t0 = time.time()

        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY tanımlı değil")

        # OpenAI messages → Gemini contents format
        contents = []
        system_texts = []          # çoklu system mesajı → hepsi birleştirilir
        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "system":
                system_texts.append(text)
                continue
            gemini_role = "user" if role == "user" else "model"
            if role == "tool" and text:
                text = f"[ARAÇ SONUCU] {text}"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": text}]
            })
        system_text = "\n\n".join(t for t in system_texts if t)

        # Yeni format anahtarlar (AQ.Ab8RN...) query parametrede reddediliyor;
        # x-goog-api-key header'ı her iki key formatıyla da çalışır.
        url = f"{self.API_BASE}/models/{self.model_name}:generateContent"

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": opts.get("temperature", 0.5),
                "maxOutputTokens": opts.get("max_tokens", 1500),
            },
        }
        if system_text:
            payload["systemInstruction"] = {
                "parts": [{"text": system_text}]
            }

        r = requests.post(url, json=payload, timeout=self.NET_TIMEOUT,
                          headers={"x-goog-api-key": self.api_key,
                                   "Content-Type": "application/json"})
        r.raise_for_status()
        data = r.json()

        # Gemini response parsing
        candidates = data.get("candidates", [])
        if not candidates:
            return ChatResponse(content="", provider=self.name, model=self.model_name)

        parts = candidates[0].get("content", {}).get("parts", [])
        content = " ".join(p.get("text", "") for p in parts).strip()

        return ChatResponse(
            content=content,
            tool_calls=[],  # Gemini: tool calling yok
            provider=self.name,
            model=self.model_name,
            latency_ms=int((time.time() - t0) * 1000),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL ROUTER — Hangi provider'ı ne zaman kullan?
# ═══════════════════════════════════════════════════════════════════════════════

class ModelRouter:
    """
    Akıllı yönlendirme:
      1. Tool gerekiyorsa → tool destekleyen provider (Groq > Ollama)
      2. Basit sohbet     → en hızlı mevcut provider (Groq > Gemini > Ollama)
      3. Offline          → Ollama (her zaman mevcut)
      4. Hiçbiri yoksa    → None (mock'a düşer)
      Provider'lar başlangıçta yoksa bile TTL ile canlı yeniden denenir.
    """

    # isim → kurucu (lazy yeniden algılama için)
    _FACTORY = {}

    def __init__(self, config: dict):
        self.config = config
        cfg = config.get("llm", {}) or {}
        self.preferred = cfg.get("provider", "auto").lower()

        # Tüm olası provider'ları oluştur
        self._providers: Dict[str, LLMProvider] = {}
        self._last_attempt: Dict[str, float] = {}   # canlı yeniden algılama için
        self._RETRY_TTL = 60.0                      # sn: başarısız provider yeniden denenir
        self._init_providers(config)

    def _ensure(self, name: str) -> bool:
        """Provider yoksa (veya daha önce yoktuysa) TTL ile yeniden dene.
        Böylece Ollama sonradan açılırsa / API key sonradan eklenirse
        uygulama yeniden başlatmadan algılanır."""
        if name in self._providers:
            return True
        now = time.time()
        if now - self._last_attempt.get(name, 0.0) < self._RETRY_TTL:
            return False
        self._last_attempt[name] = now
        factory = self._FACTORY.get(name)
        if not factory:
            return False
        try:
            p = factory(self.config)
            if p.status() == ProviderStatus.AVAILABLE:
                self._providers[name] = p
                print(f"  ✅ {name} ({getattr(p, 'model_name', '?')}) sonradan algılandı")
                return True
        except Exception as e:
            print(f"  ⚠️ {name} yeniden deneme hatası: {e}")
        return False

    def _init_providers(self, config: dict):
        """Mevcut provider'ları algıla ve kaydet."""
        # Ollama (yerel — her zaman dene)
        try:
            p = OllamaProvider(config)
            if p.status() == ProviderStatus.AVAILABLE:
                self._providers["ollama"] = p
                print(f"  ✅ Ollama ({p.model_name}) hazır")
            else:
                print(f"  ⚠️ Ollama erişilemedi")
        except Exception as e:
            print(f"  ⚠️ Ollama hata: {e}")

        # Groq (bulut — key varsa)
        try:
            p = GroqProvider(config)
            if p.status() == ProviderStatus.AVAILABLE:
                self._providers["groq"] = p
                print(f"  ✅ Groq ({p.model_name}) hazır")
            else:
                print(f"  ⚠️ Groq: API key yok (GROQ_API_KEY)")
        except Exception as e:
            print(f"  ⚠️ Groq hata: {e}")

        # Gemini (bulut — key varsa)
        try:
            p = GeminiProvider(config)
            if p.status() == ProviderStatus.AVAILABLE:
                self._providers["gemini"] = p
                print(f"  ✅ Gemini ({p.model_name}) hazır")
            else:
                print(f"  ⚠️ Gemini: API key yok (GEMINI_API_KEY)")
        except Exception as e:
            print(f"  ⚠️ Gemini hata: {e}")

        # Ücretsiz bulut zinciri: Cerebras → NVIDIA → OpenRouter (key varsa)
        for cls in (CerebrasProvider, NvidiaProvider, OpenRouterProvider):
            try:
                p = cls(config)
                if p.status() == ProviderStatus.AVAILABLE:
                    self._providers[p.name] = p
                    print(f"  ✅ {p.name.capitalize()} ({p.model_name}) hazır")
            except Exception:
                pass  # key yoksa sessizce atla

    def get_provider(self, needs_tools: bool = False) -> Optional[LLMProvider]:
        """En uygun provider'ı seç. Eksik provider'lar TTL ile canlı yeniden denenir."""

        # Kullanıcı belirli bir provider istedi
        if self.preferred not in ("auto", ""):
            if self._ensure(self.preferred):
                p = self._providers.get(self.preferred)
                if needs_tools and not p.supports_tools:
                    pass  # tool desteklemiyor → auto mantığa düş
                else:
                    return p

        # Auto routing: hız + kalite dengesine göre
        _CLOUD = ["groq", "cerebras", "gemini", "nvidia", "openrouter"]
        if needs_tools:
            # Tool calling: bulut hız sırası → yerel en son çare
            for name in _CLOUD + ["ollama"]:
                self._ensure(name)
                p = self._providers.get(name)
                if p and p.supports_tools:
                    return p
        else:
            # Sohbet: bulut zinciri → Ollama (yerel) en son
            for name in _CLOUD + ["ollama"]:
                self._ensure(name)
                p = self._providers.get(name)
                if p:
                    return p

        # Hiçbiri yoksa None — mock'a düşer
        return None

    @property
    def available_providers(self) -> List[str]:
        return list(self._providers.keys())

    @property
    def primary_provider(self) -> Optional[LLMProvider]:
        """Mevcut birincil provider."""
        return self.get_provider(needs_tools=False)

    @property
    def tool_provider(self) -> Optional[LLMProvider]:
        """Tool calling destekleyen provider."""
        return self.get_provider(needs_tools=True)


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def create_router(config: dict) -> ModelRouter:
    """Config'e göre ModelRouter oluştur."""
    print("[LLM] Provider'lar algılanıyor...")
    ModelRouter._FACTORY.update({
        "ollama": OllamaProvider,
        "groq": GroqProvider,
        "gemini": GeminiProvider,
        "cerebras": CerebrasProvider,
        "nvidia": NvidiaProvider,
        "openrouter": OpenRouterProvider,
    })
    return ModelRouter(config)
