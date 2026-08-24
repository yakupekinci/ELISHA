"""ELİŞA Uzaktan Kumanda — Mark-LI 'Remote Dashboard' esinli.
Telefondan kontrol: QR kodu okut → LAN üzerindeki mobil arayüz → yazılı komut.
Güvenlik: rastgele token zorunlu (her istekte); settings'ten kapatılabilir.
"""
import json
import secrets
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from elisha import settings
from elisha.log import log

_server = None
_last_replies = []          # son yanıtlar (mobil poll için)
_reply_lock = threading.Lock()
MAX_REPLIES = 30


def get_token() -> str:
    tok = str(settings.get("remote_token") or "")
    if not tok:
        tok = secrets.token_hex(16)
        settings.set_many({"remote_token": tok})
    return tok


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def dashboard_url() -> str:
    return f"http://{lan_ip()}:8766/?t={get_token()}"


def push_reply(text: str):
    with _reply_lock:
        _last_replies.append({"ts": time_time(), "text": str(text)[:600]})
        del _last_replies[:-MAX_REPLIES]


def time_time():
    import time
    return time.time()


_PAGE = """<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>ELİŞA Kumanda</title><style>
:root{--bg:#050510;--p:rgba(13,17,36,.7);--b:rgba(150,168,205,.18);--f:#e8eefb;--m:#9db0cc;--a:#38e1ff}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--f);font-family:-apple-system,system-ui,sans-serif;
  height:100dvh;display:flex;flex-direction:column}
header{padding:14px 16px;border-bottom:1px solid var(--b);display:flex;gap:10px;align-items:center}
header .d{width:10px;height:10px;border-radius:50%;background:var(--a);box-shadow:0 0 10px var(--a)}
header b{letter-spacing:.28em;font-size:14px}
header span{color:var(--m);font-size:11px;margin-left:auto}
#log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px}
.m{max-width:85%;padding:9px 13px;border-radius:16px;line-height:1.45;font-size:14.5px;word-wrap:break-word}
.u{align-self:flex-end;background:rgba(91,140,255,.28)}
.a{align-self:flex-start;background:var(--p);border:1px solid var(--b)}
.s{align-self:center;color:var(--m);font-size:11.5px}
footer{padding:10px 12px calc(12px + env(safe-area-inset-bottom));border-top:1px solid var(--b);
  display:flex;gap:8px}
input{flex:1;background:var(--p);border:1px solid var(--b);border-radius:22px;color:var(--f);
  padding:11px 15px;font-size:15px;outline:none}
button{width:46px;height:46px;border-radius:50%;border:none;background:var(--a);color:#041019;
  font-size:18px;cursor:pointer}
.q{display:flex;gap:6px;flex-wrap:wrap;padding:0 12px 8px}
.q button{width:auto;height:30px;border-radius:14px;background:var(--p);color:var(--m);
  border:1px solid var(--b);font-size:11.5px;padding:0 11px}
</style></head><body>
<header><div class="d"></div><b>ELİŞA</b><span id="st">bağlanıyor</span></header>
<div id="log"><div class="s">📱 Uzaktan kumanda bağlı — yazarak konuş</div></div>
<div class="q">
  <button onclick="q('saat kaç')">⏰ saat</button>
  <button onclick="q('hava durumu')">🌤 hava</button>
  <button onclick="q('dolar kaç lira')">💱 döviz</button>
  <button onclick="q('ekranıma bak')">👁 ekran</button>
  <button onclick="q('Mac ısındı mı')">📊 sistem</button>
</div>
<footer><input id="i" placeholder="ELİŞA'ya yaz…" autocomplete="off">
<button onclick="send()">➤</button></footer>
<script>
const t = new URLSearchParams(location.search).get('t')||'';
const log = document.getElementById('log');
function add(cls, txt){ const d=document.createElement('div'); d.className='m '+cls;
  d.textContent=txt; log.appendChild(d); log.scrollTop=log.scrollHeight; }
async function send(){ const i=document.getElementById('i'); const v=i.value.trim();
  if(!v) return; i.value=''; add('u',v);
  try{
    const r = await fetch('/api/cmd?t='+encodeURIComponent(t),{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({text:v})});
    if(r.status===403){ add('s','⛔ Token geçersiz — QR kodu yeniden okut'); return; }
    const j = await r.json();
    add('a', j.reply || j.error || '(boş yanıt)');
  }catch(e){ add('s','⚠️ Bağlantı hatası'); }
}
function q(v){ document.getElementById('i').value=v; send(); }
document.getElementById('i').addEventListener('keypress',e=>{ if(e.key==='Enter') send(); });
(async function poll(){ try{
    const r = await fetch('/api/poll?t='+encodeURIComponent(t));
    if(r.ok){ const j = await r.json();
      document.getElementById('st').textContent='bağlı';
      if(j.reply && j.reply !== poll._last){ add('a', j.reply); poll._last = j.reply; } }
  }catch(e){ document.getElementById('st').textContent='bağlantı yok'; }
  setTimeout(poll, 2500); })();
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _auth(self) -> bool:
        q = urllib.parse.urlparse(self.path).query
        tok = urllib.parse.parse_qs(q).get("t", [""])[0]
        return bool(tok) and tok == get_token()

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            if not self._auth():
                self._send(403, "⛔ Geçersiz bağlantı — QR kodu yeniden okut.".encode(),
                           "text/plain; charset=utf-8")
                return
            self._send(200, _PAGE.encode(), "text/html; charset=utf-8")
            return
        if not self._auth():
            self._send(403, b'{"error":"forbidden"}')
            return
        if parsed.path == "/api/poll":
            with _reply_lock:
                last = _last_replies[-1] if _last_replies else None
            self._send(200, json.dumps({"reply": last["text"] if last else ""}).encode())
            return
        self._send(404, b'{}')

    def do_POST(self):
        if not self._auth():
            self._send(403, b'{"error":"forbidden"}')
            return
        if urllib.parse.urlparse(self.path).path != "/api/cmd":
            self._send(404, b'{}')
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            text = str(data.get("text", "")).strip()
            if not text:
                return self._send(400, b'{"error":"empty"}')
        except Exception:
            return self._send(400, b'{"error":"bad json"}')

        def work():
            try:
                from app.server import get_bot
                reply = get_bot().process_text(text)
                push_reply(reply or "Tamam.")
                log("REMOTE", f"📱 {text[:50]} → {(reply or '')[:50]}")
            except Exception as e:
                push_reply(f"Hata: {e}")
        threading.Thread(target=work, daemon=True).start()
        self._send(200, b'{"ok":true}')

    def log_message(self, *a):
        pass


def start():
    """LAN dinleyicisini başlat (settings remote_enabled=false ise başlamaz)."""
    global _server
    if str(settings.get("remote_enabled", True)) in ("0", "false", "False"):
        log("REMOTE", "📱 uzaktan kumanda ayarlardan kapalı")
        return
    try:
        _server = ThreadingHTTPServer(("0.0.0.0", 8766), _Handler)
        threading.Thread(target=_server.serve_forever, daemon=True).start()
        log("REMOTE", f"📱 kumanda canlı → {dashboard_url()}")
    except Exception as e:
        log("REMOTE", f"başlatılamadı: {e}")


def make_qr(path: str = "/tmp/elisha_dashboard_qr.png") -> str:
    import qrcode
    img = qrcode.make(dashboard_url())
    img.save(path)
    return path
