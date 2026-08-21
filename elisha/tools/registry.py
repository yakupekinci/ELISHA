from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult


class ToolRegistry:
    def __init__(self, config: dict):
        self.config = config
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool zaten kayıtlı: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def to_ollama_tools(self) -> List[Dict[str, Any]]:
        tools = []
        for t in self._tools.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return tools

    def execute(self, name: str, args: Optional[Dict[str, Any]] = None) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, name, error=f"Bilinmeyen araç: {name}")
        return tool.safe_run(args or {})

    def describe_all(self) -> str:
        lines = []
        for t in self._tools.values():
            params = ", ".join(t.parameters.get("properties", {}).keys()) or "-"
            lines.append(f"- {t.name}({params}) [{t.risk_level.value}]: {t.description}")
        return "\n".join(lines)
