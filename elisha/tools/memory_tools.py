from typing import Any, Dict

from .base import Tool, ToolResult, RiskLevel


class RememberTool(Tool):
    name = "remember"
    description = ("Kullanıcı hakkında önemli bir bilgiyi KALICI olarak hafızaya kaydeder. "
                   "Kullanıcı 'bunu hatırla', 'aklında tut' derse veya kalıcı bilgi paylaşırsa kullan: "
                   "meslek, projeler, tercihler, isim vb. key kısa bir başlık (örn. 'oyun motoru'), "
                   "value kaydedilecek bilginin kendisi.")
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Bilginin kısa başlığı, örn. 'oyun motoru'"},
            "value": {"type": "string", "description": "Hatırlanacak bilginin kendisi"},
            "category": {"type": "string", "description": "Kategori: kisi, proje, tercih, genel"},
        },
        "required": ["key", "value"],
    }
    risk_level = RiskLevel.LOW

    def __init__(self, config: dict, store):
        super().__init__(config)
        self.store = store

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        key = str(args.get("key", "")).strip()
        value = str(args.get("value", "")).strip()
        category = str(args.get("category", "") or "genel").strip()
        if self.store is None:
            return ToolResult(False, self.name, error="Hafıza kapalı.")
        if self.store.remember(key, value, category):
            return ToolResult(True, self.name,
                              message=f"Akılda tuttum: {key} = {value}",
                              data={"key": key, "value": value})
        return ToolResult(False, self.name, error="Kaydedilemedi.")


class RecallTool(Tool):
    name = "recall"
    description = ("Hafızadaki bilgileri arar/getirir. Kullanıcı 'ben ne yapıyorum', 'hatıyor musun', "
                   "'X nedir benim için' gibi sorular sorarsa ve cevabı hatırlarındaysa kullan. "
                   "query boşsa en önemli kayıtları getirir.")
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Aranacak konu (boş olabilir)"},
        },
        "required": [],
    }
    risk_level = RiskLevel.SAFE

    def __init__(self, config: dict, store):
        super().__init__(config)
        self.store = store

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        if self.store is None:
            return ToolResult(False, self.name, error="Hafıza kapalı.")
        query = str(args.get("query", "") or "").strip()
        items = self.store.recall(query, limit=8)
        if not items:
            return ToolResult(True, self.name,
                              message="Bu konuda kayıtlı bir şey bulamadım.",
                              data={"results": []})
        lines = [f"- ({it['category']}) {it['key']}: {it['value']}" for it in items]
        return ToolResult(True, self.name,
                          message="Hatırladıklarım:\n" + "\n".join(lines),
                          data={"count": len(items), "results": items})


class ForgetTool(Tool):
    name = "forget"
    description = ("Hafızadan bir bilgiyi siler. Kullanıcı 'bunu unut', 'X'i unut' derse kullan. "
                   "query silinecek kaydın anahtar kelimesi ya da içinde geçen ifade.")
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Unutulacak bilginin adı/içeriği"},
        },
        "required": ["query"],
    }
    risk_level = RiskLevel.MEDIUM

    def __init__(self, config: dict, store):
        super().__init__(config)
        self.store = store

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        if self.store is None:
            return ToolResult(False, self.name, error="Hafıza kapalı.")
        query = str(args.get("query", "")).strip()
        n = self.store.forget(query)
        if n > 0:
            return ToolResult(True, self.name,
                              message=f"Tamam, {n} kaydı unuttum.", data={"deleted": n})
        return ToolResult(False, self.name, error="Böyle bir kayıt bulamadım.")
