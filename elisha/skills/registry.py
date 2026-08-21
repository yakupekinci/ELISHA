import re
from .system import SystemSkill
from .files import FilesSkill

class SkillRegistry:
    def __init__(self, config: dict):
        self.config = config
        self.skills = [
            SystemSkill(config),
            FilesSkill(config),
        ]
        # websearch ayrı (opsiyonel, duckduckgo-search yoksa atla)

    def parse_actions(self, text: str):
        """
        LLM çıktısından [ACTION: name | k=v | ...] bloklarını çıkar
        returns [(action, params), ...]
        """
        pattern = r"\[ACTION:\s*([^\]|]+)(?:\s*\|\s*([^\]]+))?\]"
        actions = []
        for m in re.finditer(pattern, text):
            action = m.group(1).strip()
            raw_params = m.group(2) or ""
            params = {}
            for part in raw_params.split("|"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k.strip()] = v.strip().strip('"').strip("'")
                elif part:
                    params[part] = True
            actions.append((action, params))
        return actions

    def strip_actions(self, text: str) -> str:
        return re.sub(r"\[ACTION:[^\]]+\]", "", text).strip()

    def execute(self, action: str, params: dict) -> str:
        # websearch özel
        if action == "web_search":
            return self._web_search(params.get("query", ""))
        for skill in self.skills:
            if skill.can_handle(action):
                return skill.execute(action, params)
        return f"Bilinmeyen eylem: {action}"

    def _web_search(self, query: str) -> str:
        if not query:
            return "Arama sorgusu boş."
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            if not results:
                return f"'{query}' için sonuç bulunamadı."
            lines = []
            for i, r in enumerate(results[:3], 1):
                title = r.get("title", "")
                body = r.get("body", "")[:180]
                href = r.get("href", "")
                lines.append(f"{i}. {title}\n   {body}\n   {href}")
            return f"'{query}' için sonuçlar:\n" + "\n".join(lines)
        except Exception as e:
            # fallback: sadece query dön
            return f"Web araması hatası: {e} — sorgu: {query}"

    def handle_text(self, llm_text: str):
        """
        LLM text -> (temiz cevap, skill sonuçları)
        """
        actions = self.parse_actions(llm_text)
        clean = self.strip_actions(llm_text)
        results = []
        for act, params in actions:
            print(f"⚙️ Skill çalışıyor: {act} {params}")
            res = self.execute(act, params)
            results.append(res)
            print(f"   -> {res[:200]}")
        return clean, results
