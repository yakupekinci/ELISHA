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
                 memory_store=None):
        self.config = config
        self.host = llm_host
        self.model = llm_model
        self.registry = registry
        self.on_status = on_status or (lambda s: None)
        self.permissions = permissions or PermissionManager(config)
        self.memory = memory_store
        agent_cfg = config.get("agent", {}) or {}
        self.enabled = bool(agent_cfg.get("enabled", True))
        self.max_steps = int(agent_cfg.get("max_steps", 8))
        self.temperature = float((config.get("llm", {}) or {}).get("temperature", 0.7))
        self.max_tokens = int((config.get("llm", {}) or {}).get("max_tokens", 512))
        self.system_prompt = ((config.get("llm", {}) or {}).get("agent_system_prompt")
                              or AGENT_PROMPT_TR)

    def _status(self, text: str):
        try:
            self.on_status(text)
        except Exception:
            pass

    def run(self, user_text: str, history: Optional[List[Dict[str, str]]] = None) -> AgentResult:
        tools = self.registry.to_ollama_tools()
        system_prompt = self.system_prompt
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

            if not tool_calls:
                final = content or "Bir şey diyemedim."
                steps.append(AgentStep("final", detail=final[:200]))
                return AgentResult(final, steps, executed)

            messages.append({"role": "assistant",
                             "content": content,
                             "tool_calls": tool_calls})

            for call in tool_calls:
                fn = (call.get("function") or {})
                name = fn.get("name", "")
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
                    messages.append({"role": "tool", "content": result_text})
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
                messages.append({"role": "tool", "content": result_text})

    def _chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "tools": tools,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        r = requests.post(f"{self.host}/api/chat", json=payload, timeout=90)
        r.raise_for_status()
        return r.json().get("message", {})

    def _force_summary(self, messages: List[Dict[str, Any]]) -> str:
        msgs = [m for m in messages]
        msgs.append({"role": "user",
                     "content": "Adım limitine ulaştık. Şimdiye kadar yaptıklarını ve elde edilen "
                                "sonuçları KISA bir cümleyle kullanıcıya özetle. Yeni araç çağırma."})
        try:
            payload = {
                "model": self.model,
                "messages": msgs,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 200},
            }
            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=60)
            r.raise_for_status()
            return (r.json().get("message", {}).get("content") or "").strip() or \
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
