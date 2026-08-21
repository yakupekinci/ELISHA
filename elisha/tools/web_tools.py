import re
from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


class WebSearchTool(Tool):
    name = "web_search"
    description = ("İnternette DuckDuckGo ile arama yapar. Güncel bilgi, hava durumu, haberler, "
                   "'kimdir/nedir' soruları ve bilmediğin her konu için kullan. Asla bilgi uydurma; "
                   "bilmiyorsan bu aracı kullan. query parametresi zorunlu.")
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Arama sorgusu"}},
        "required": ["query"],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(False, self.name, error="Arama sorgusu boş.")
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            if not results:
                return ToolResult(False, self.name, error=f"'{query}' için sonuç bulunamadı.")
            items = []
            for r in results[:3]:
                items.append({
                    "title": r.get("title", ""),
                    "body": (r.get("body", "") or "")[:180],
                    "url": r.get("href", ""),
                })
            lines = [f"{i}. {it['title']}\n   {it['body']}\n   {it['url']}"
                     for i, it in enumerate(items, 1)]
            return ToolResult(True, self.name,
                              message=f"'{query}' için sonuçlar:\n" + "\n".join(lines),
                              data={"query": query, "results": items})
        except Exception as e:
            return ToolResult(False, self.name, error=f"Web araması hatası: {e}")


class FetchWebpageTool(Tool):
    name = "fetch_webpage"
    description = ("Bir web sayfasının metin içeriğini çeker ve okunabilir hale getirir. "
                   "web_search sonuçlarındaki bir sayfanın detayını okumak veya kullanıcı bir adresin "
                   "içeriğini isterse kullan. url parametresi zorunlu.")
    parameters = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Çekilecek sayfa adresi"}},
        "required": ["url"],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        url = str(args.get("url", "")).strip()
        if not url:
            return ToolResult(False, self.name, error="URL boş.")
        if not url.startswith("http"):
            url = "https://" + url
        try:
            import requests
            headers = {"User-Agent": "Mozilla/5.0 (ELISHA local assistant)"}
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            html = r.text
            html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            truncated = len(text) > 3000
            shown = text[:3000] + ("... (kısaltıldı)" if truncated else "")
            if not shown:
                return ToolResult(False, self.name, error="Sayfa içeriği okunamadı.")
            return ToolResult(True, self.name, message=shown,
                              data={"url": url, "length": len(text), "truncated": truncated})
        except Exception as e:
            return ToolResult(False, self.name, error=f"Sayfa çekilemedi: {e}")
