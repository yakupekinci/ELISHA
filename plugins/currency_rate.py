"""Döviz kuru eklentisi — frankfurter.app (ECB verisi, anahtarsız)."""

PLUGIN = {
    "name": "currency_rate",
    "description": (
        "Güncel döviz kuru sorguları için kullanılır: 'dolar kaç lira', 'euro kuru', "
        "'sterlin kaç TL', '100 dolar kaç euro' gibi. Kullanıcı crypto (bitcoin vb.) "
        "sorarsa KULLANMA, web_search kullan."),
    "parameters": {
        "type": "object",
        "properties": {
            "from_currency": {
                "type": "string",
                "description": "Kaynak para birimi kodu: USD, EUR, GBP vb. (varsayılan USD)"
            },
            "to_currency": {
                "type": "string",
                "description": "Hedef para birimi kodu (varsayılan TRY)"
            },
            "amount": {
                "type": "number",
                "description": "Çevrilecek miktar (varsayılan 1)"
            },
        },
        "required": [],
    },
    "risk": "LOW",
}

_KNOWN = {"usd": "USD", "dolar": "USD", "dollar": "USD",
          "eur": "EUR", "euro": "EUR", "avro": "EUR",
          "gbp": "GBP", "sterlin": "GBP", "pound": "GBP",
          "try": "TRY", "tl": "TRY", "lira": "TRY", "türk lirası": "TRY",
          "chf": "CHF", "frank": "CHF", "jpy": "JPY", "yen": "JPY",
          "aud": "AUD", "cad": "CAD", "sar": "SAR"}


def _norm(code: str) -> str:
    return _KNOWN.get(str(code or "").lower().strip(), str(code or "").upper() or "USD")


def run(parameters: dict) -> str:
    import requests
    try:
        src = _norm(parameters.get("from_currency") or "USD")
        dst = _norm(parameters.get("to_currency") or "TRY")
        try:
            amount = float(parameters.get("amount") or 1)
        except (TypeError, ValueError):
            amount = 1.0
        r = requests.get(f"https://api.frankfurter.app/latest",
                         params={"from": src, "to": dst}, timeout=8)
        r.raise_for_status()
        data = r.json()
        rate = (data.get("rates") or {}).get(dst)
        if not rate:
            return f"{src} → {dst} kuru bulunamadı."
        total = rate * amount
        if amount == 1:
            return f"1 {src} = {rate:.2f} {dst} (ECB güncel kur)"
        return (f"{amount:g} {src} = {total:,.2f} {dst} "
                f"(kur: 1 {src} = {rate:.2f} {dst})")
    except Exception as e:
        return f"Döviz kuru alınamadı: {e}"
