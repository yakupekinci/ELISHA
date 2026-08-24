"""ELİŞA Sabah Brifingi — Mark-LI 'Morning Briefing' + 'Session Memory' esinli.
Günde bir kez (05:00–12:00 arası ilk etkileşimde): selam + tarih + hava +
dünkü son konuşmadan kısa hatıra + gündem başlığı. Her bölüm ayrı korunur —
bir kaynak başarısızsa brifing yine de güzel çıkar."""
import datetime
import xml.etree.ElementTree as ET

from .log import log


def _selam(now) -> str:
    h = now.hour
    if h < 6:
        return "Gece yarıları bile ayaktayız demek"
    if h < 12:
        return "Günaydın"
    if h < 18:
        return "İyi günler"
    return "İyi akşamlar"


def _hava(city: str = "istanbul") -> str:
    try:
        import requests
        r = requests.get(f"https://wttr.in/{city}?format=%c+%t",
                         timeout=5, headers={"User-Agent": "curl/8"})
        if r.status_code == 200 and r.text.strip():
            return f"Hava durumu: {r.text.strip()}"
    except Exception:
        pass
    return ""


def _dun(memory_store) -> str:
    try:
        msgs = memory_store.recent_messages(limit=30) if memory_store else []
        seen, topics = set(), []
        for m in msgs:
            if m.get("role") != "user":
                continue
            t = str(m["content"]).strip()
            if len(t) < 8:
                continue
            key = t[:40].lower()
            if key in seen:
                continue
            seen.add(key)
            topics.append(t[:70])
            if len(topics) >= 2:
                break
        if topics:
            return ("Dün şunları konuşmuştuk: \""
                    + "\" ve \"".join(topics) + "\"…")
    except Exception:
        pass
    return ""


def _gundem() -> str:
    try:
        import requests
        r = requests.get("https://www.trthaber.com/sondakika.rss",
                         timeout=6, headers={"User-Agent": "curl/8"})
        root = ET.fromstring(r.content)
        title = root.find(".//item/title")
        if title is not None and title.text:
            return f"Gündemdeki son haber: {title.text.strip()}"
    except Exception:
        pass
    return ""


def compose(config: dict, memory_store=None) -> str:
    now = datetime.datetime.now()
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    aylar = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    tarih = f"{now.day} {aylar[now.month]} {now.year} {gunler[now.weekday()]}"

    parts = [f"{_selam(now)}! Bugün {tarih}."]
    city = "istanbul"
    try:
        from . import settings as _settings
        city = str(_settings.get("briefing_city") or city)
    except Exception:
        pass
    hv = _hava(city)
    if hv:
        parts.append(hv)
    dun = _dun(memory_store)
    if dun:
        parts.append(dun)
    g = _gundem()
    if g:
        parts.append(g)
    parts.append("Bugün için ne yapmamı istersin?")
    text = " ".join(p for p in parts if p)
    log("BRIEFING", f"🌅 {text[:120]}")
    return text
