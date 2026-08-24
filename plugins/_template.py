"""ELİŞA eklenti şablonu.

Bu dosyayı kopyala, adını değiştir (başında _ olmasın), PLUGIN ve run() doldur.
Restart'ta otomatik keşfedilir — başka hiçbir dosyaya dokunma.
"""

PLUGIN = {
    "name": "ornek_araç",                    # benzersiz snake_case
    "description": (
        "LLM'in bu aracı ne zaman kullanacağına karar vermesi için 1-2 cümle. "
        "Tetikleyici ifadeleri açıkça yaz."),
    "parameters": {
        "type": "object",
        "properties": {
            "ornek_arg": {"type": "string", "description": "Argüman ne işe yarar"},
        },
        "required": [],
    },
    "risk": "LOW",  # SAFE / LOW / MEDIUM / HIGH — HIGH onay ister
}


def run(parameters: dict) -> str:
    """parameters: LLM'in çıkardığı argümanlar.
    Kullanıcıya söylenecek doğal metni döndür. Hataları yakala, asla raise etme."""
    ornek = parameters.get("ornek_arg", "")
    try:
        return f"Örnek işlem tamam: {ornek}"
    except Exception as e:
        return f"Eklenti hata verdi: {e}"
