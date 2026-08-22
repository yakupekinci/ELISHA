import re
import ssl
from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


def _patch_ddgs_tls():
    """LibreSSL 2.8.3 TLS 1.3 desteklemiyor — ddgs'nin TLSv1_3 minimum_version kullanmasını engelle."""
    try:
        import ddgs.http_client2 as _hc
        import inspect, types
        src = inspect.getsource(_hc._get_random_ssl_context)
        if "TLSv1_3" not in src:
            return  # zaten yamanlı
        # Yeni versiyon: TLSv1_3 olmadan
        def _get_random_ssl_context_patched(verify):
            import random as _r
            ctx = ssl.create_default_context(cafile=verify if isinstance(verify, str) else None)
            commands = [
                lambda c: None,
                lambda c: setattr(c, "maximum_version", ssl.TLSVersion.TLSv1_2),
                lambda c: setattr(c, "options", c.options | ssl.OP_NO_TICKET),
            ]
            _r.choice(commands)(ctx)
            return ctx
        _hc._get_random_ssl_context = _get_random_ssl_context_patched
    except Exception:
        pass


_patch_ddgs_tls()


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
                results = list(ddgs.text(query, region="tr-tr", max_results=5))
            if not results:  # Türkçe bölge boşsa global dene
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
