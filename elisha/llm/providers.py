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
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            available = [m["name"] for m in r.json().get("models", [])]
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

    def __init__(self, config: dict):
        cfg = config.get("llm", {}) or {}
        self.model_name = cfg.get("groq_model", "llama-3.3-70b-versatile")
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

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": opts.get("temperature", 0.5),
            "max_tokens": opts.get("max_tokens", 1500),
        }
        if oai_tools:
            payload["tools"] = oai_tools
            payload["tool_choice"] = "auto"

        r = requests.post(self.API_URL, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = (msg.get("content") or "").strip()

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


# ═══════════════════════════════════════════════════════════════════════════════
# GEMINI PROVIDER (Bulut — ücretsiz, iyi Türkçe, sadece sohbet)
# ═══════════════════════════════════════════════════════════════════════════════

class GeminiProvider(LLMProvider):
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
        self.model_name = cfg.get("gemini_model", "gemini-2.0-flash")
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
        system_text = ""
        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "system":
                system_text = text
                continue
            gemini_role = "user" if role == "user" else "model"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": text}]
            })

        url = f"{self.API_BASE}/models/{self.model_name}:generateContent?key={self.api_key}"

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

        r = requests.post(url, json=payload, timeout=30)
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
    """

    def __init__(self, config: dict):
        self.config = config
        cfg = config.get("llm", {}) or {}
        self.preferred = cfg.get("provider", "auto").lower()

        # Tüm olası provider'ları oluştur
        self._providers: Dict[str, LLMProvider] = {}
        self._init_providers(config)

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

    def get_provider(self, needs_tools: bool = False) -> Optional[LLMProvider]:
        """En uygun provider'ı seç."""

        # Kullanıcı belirli bir provider istedi
        if self.preferred not in ("auto", ""):
            p = self._providers.get(self.preferred)
            if p:
                if needs_tools and not p.supports_tools:
                    # Tool gerekli ama provider desteklemiyor → tool destekleyen bul
                    pass
                else:
                    return p

        # Auto routing: hız + kalite dengesine göre
        if needs_tools:
            # Tool calling: Groq (hızlı) > Ollama (yerel)
            for name in ["groq", "ollama"]:
                p = self._providers.get(name)
                if p and p.supports_tools:
                    return p
        else:
            # Sohbet: Groq (hızlı+akıllı) > Gemini (iyi Türkçe) > Ollama (yerel)
            for name in ["groq", "gemini", "ollama"]:
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
    return ModelRouter(config)
