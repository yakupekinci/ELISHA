import time
from typing import Any, Dict, Optional

from .tools.base import ToolResult


CONFIRM_WORDS = {"evet", "onayla", "onaylıyorum", "onayliyorum", "tamam", "tamamdır",
                 "okey", "ok", "oldu", "devam", "devam et", "yap", "sil"}
DENY_WORDS = {"hayır", "hayir", "vazgeç", "vazgec", "iptal", "dur", "olmasın",
              "olmasin", "asla", "yeniden düşün", "iptal et"}


class NeedConfirmation(Exception):
    """HIGH/CRITICAL araç çağrısı kullanıcı onayı bekliyor."""

    def __init__(self, tool_name: str, args: Dict[str, Any], message: str):
        self.tool_name = tool_name
        self.args = args
        self.message = message
        super().__init__(message)


class PermissionManager:
    """Python tarafında zorunlu kılan onay katmanı. LLM bu katmanı bypass edemez."""

    def __init__(self, config: dict):
        self.config = config
        sec = config.get("security", {}) or {}
        self.required_levels = set(sec.get("require_confirmation_for", ["HIGH", "CRITICAL"]))
        self.pending: Optional[Dict[str, Any]] = None
        self.pending_ttl = 120  # saniye

    def _tool(self, registry, name):
        return registry.get(name)

    def needs_confirmation(self, registry, name: str) -> bool:
        tool = self._tool(registry, name)
        if tool is None:
            return False
        return tool.risk_level.value in self.required_levels

    def build_question(self, registry, name: str, args: Dict[str, Any]) -> str:
        tool = self._tool(registry, name)
        if tool is not None:
            try:
                return tool.confirm_message(args)
            except Exception:
                pass
        return f"'{name}' işlemi onay bekliyor. Onaylıyor musun?"

    def request(self, name: str, args: Dict[str, Any], question: str):
        self.pending = {
            "tool": name,
            "args": args,
            "question": question,
            "ts": time.time(),
        }

    def has_pending(self) -> bool:
        if self.pending is None:
            return False
        if time.time() - self.pending["ts"] > self.pending_ttl:
            self.pending = None
            return False
        return True

    def classify_reply(self, text: str) -> Optional[bool]:
        t = (text or "").lower().strip().strip(".!")
        if any(w == t or (w in t and len(t) <= 25) for w in CONFIRM_WORDS):
            return True
        for w in DENY_WORDS:
            if w == t or (w in t and len(t) <= 25):
                return False
        return None

    def resolve(self, registry, user_text: str) -> Optional[ToolResult]:
        """Bekleyen onay varsa kullanıcı cevabını değerlendirip aracı çalıştırır."""
        if not self.has_pending():
            return None
        decision = self.classify_reply(user_text)
        if decision is None:
            return None
        item = self.pending
        self.pending = None
        if not decision:
            return ToolResult(True, item["tool"],
                              message="Tamam, işlemi iptal ettim.",
                              data={"cancelled": True})
        return registry.execute(item["tool"], item["args"])
