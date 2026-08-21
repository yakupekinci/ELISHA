from enum import Enum
from typing import Any, Dict, Optional


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolResult:
    def __init__(self, success: bool, tool: str, message: str = "",
                 data: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        self.success = success
        self.tool = tool
        self.message = message
        self.data = data or {}
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        d = {"success": self.success, "tool": self.tool}
        if self.data:
            d["data"] = self.data
        if self.error:
            d["error"] = self.error
        if self.message:
            d["message"] = self.message
        return d

    def for_llm(self) -> str:
        if not self.success:
            return "HATA: " + (self.error or self.message or "bilinmeyen hata")
        parts = [self.message] if self.message else []
        if self.data:
            for k, v in self.data.items():
                parts.append(f"{k}: {v}")
        return "\n".join(parts) if parts else "Tamam."

    def __repr__(self):
        return f"ToolResult(success={self.success}, tool={self.tool}, message={self.message!r})"


class Tool:
    name: str = "tool"
    description: str = ""
    parameters: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    risk_level: RiskLevel = RiskLevel.SAFE

    def __init__(self, config: dict):
        self.config = config

    @property
    def requires_confirmation(self) -> bool:
        sec = self.config.get("security", {}) or {}
        required = sec.get("require_confirmation_for", ["HIGH", "CRITICAL"])
        return self.risk_level.value in required

    def confirm_message(self, args: Dict[str, Any]) -> str:
        return f"'{self.name}' işlemi onay bekliyor. Onaylıyor musun?"

    def validate_args(self, args: Dict[str, Any]) -> Optional[str]:
        args = args or {}
        schema = self.parameters or {}
        props = schema.get("properties", {}) or {}
        for req in schema.get("required", []) or []:
            if req not in args or args[req] in (None, ""):
                return f"Eksik parametre: '{req}' zorunlu."
        type_map = {"string": str, "number": float, "integer": int,
                    "boolean": bool, "array": list, "object": dict}
        for key, val in args.items():
            if key not in props:
                continue
            expected = props[key].get("type")
            pytype = type_map.get(expected)
            if pytype is None:
                continue
            if expected == "integer" and isinstance(val, float) and val.is_integer():
                continue
            if expected == "number" and isinstance(val, int):
                continue
            if not isinstance(val, pytype):
                return f"Parametre '{key}' {expected} olmalı, {type(val).__name__} geldi."
        return None

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def safe_run(self, args: Dict[str, Any]) -> ToolResult:
        err = self.validate_args(args)
        if err:
            return ToolResult(False, self.name, error=err)
        try:
            return self.execute(args or {})
        except Exception as e:
            return ToolResult(False, self.name, error=f"{type(e).__name__}: {e}")
