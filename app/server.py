"""
ELİŞA Web Server — Threading + cache + local STT
Çalıştır: python3 app/server.py  -> http://localhost:8765
"""
import json, base64, tempfile, threading, time, queue
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.orchestrator import ElishaOrchestrator

PORT = 8765
WEB_DIR = Path(__file__).parent / "web"

# Aktif SSE istemciler (agent durum yayını)
_sse_clients = set()
_sse_lock = threading.Lock()

_bot = None
_bot_lock = threading.Lock()
def get_bot():
    global _bot
    with _bot_lock:
        if _bot is None:
            print("ELİŞA yükleniyor...")
            _bot = ElishaOrchestrator()
            print(f"ELİŞA hazır: {_bot.stt.provider} / {_bot.tts.provider} / {_bot.llm.provider}")
    return _bot

# Piper voice cache (her istekte yeniden yükleme!)
_piper_voice = None
_piper_lock = threading.Lock()
def get_piper():
    global _piper_voice
    with _piper_lock:
        if _piper_voice is None:
            from piper import PiperVoice
            model = Path("./voices/tr_TR-dfki-medium.onnx").resolve()
            if not model.exists():
                raise FileNotFoundError(f"piper model yok: {model}")
            _piper_voice = PiperVoice.load(str(model))
            print("✅ Piper cache'lendi")
    return _piper_voice

# LLM chat lock — aynı anda tek istek işlensin (Ollama güvenliği)
_chat_lock = threading.Lock()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB_DIR), **kw)

    def log_message(self, fmt, *args):
        # poll spamini gizle
        try:
            line = fmt % args if args else fmt
        except Exception:
            line = str(args)
        if "/api/wake_check" in line or "/api/health" in line:
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200); self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/status":
                bot = get_bot()
                self._json(200, {"name": "ELİŞA", "stt": bot.stt.provider, "tts": bot.tts.provider,
                                 "llm": bot.llm.provider, "wake": "hey elişa uyan"})
                return
            if parsed.path == "/api/health":
                self._json(200, {"ok": True})
                return
            if parsed.path == "/api/wake_check":
                p = Path("/tmp/elisha_wake")
                if p.exists():
                    try:
                        txt = p.read_text().strip(); p.unlink()
                        self._json(200, {"wake": True, "text": txt}); return
                    except: pass
                self._json(200, {"wake": False})
                return
            if parsed.path == "/api/wake_enable":
                Path("/tmp/elisha_wake_enabled").write_text("1")
                self._json(200, {"enabled": True})
                return
            if parsed.path == "/api/wake_disable":
                try: Path("/tmp/elisha_wake_enabled").unlink()
                except: pass
                self._json(200, {"enabled": False})
                return
        except Exception as e:
            self._json(500, {"error": str(e)})
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")

        try:
            if parsed.path == "/api/chat":
                data = json.loads(body) if body else {}
                text = (data.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": "no text"})
                bot = get_bot()
                with _chat_lock:  # LLM seri çalışsın, history bozulmasın
                    reply = bot.process_text(text)
                self._json(200, {"reply": reply, "text": text})
                return

            if parsed.path == "/api/chat_stream":
                # SSE: status olayları + kademeli final cevap
                data = json.loads(body) if body else {}
                text = (data.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": "no text"})
                bot = get_bot()
                self._chat_stream_sse(bot, text)
                return

            if parsed.path == "/api/tts":
                data = json.loads(body) if body else {}
                text = (data.get("text") or "").strip()[:500]
                if not text:
                    return self._json(400, {"error": "no text"})
                import numpy as np, soundfile as sf
                voice = get_piper()
                chunks = list(voice.synthesize(text))
                audio = np.concatenate([np.array(c.audio_float_array) for c in chunks])
                sr = chunks[0].sample_rate
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    sf.write(tf.name, audio, sr)
                    wav_bytes = Path(tf.name).read_bytes()
                    Path(tf.name).unlink()
                self._json(200, {"audio": base64.b64encode(wav_bytes).decode(), "sr": sr})
                return

            if parsed.path == "/api/stt":
                # browser MediaRecorder'dan gelen ses (webm/opus) -> local whisper
                if not body:
                    return self._json(400, {"error": "no audio"})
                suffix = ".webm" if "webm" in ctype else ".wav"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    tf.write(body); tmp_path = tf.name
                try:
                    bot = get_bot()
                    segments, info = bot.stt.transcribe_file_full(tmp_path)
                    text = " ".join(segments).strip()
                    self._json(200, {"text": text, "language": info})
                finally:
                    try: Path(tmp_path).unlink()
                    except: pass
                return

            self._json(404, {"error": "not found"})
        except Exception as e:
            import traceback; traceback.print_exc()
            self._json(500, {"error": str(e)})

    def _json(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    # ---------- SSE streaming chat ----------

    def _sse_send(self, obj):
        try:
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    def _chat_stream_sse(self, bot, text):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = queue.Queue()

        def on_status(s):
            q.put(("status", s))

        def worker():
            old_cb = getattr(bot, "status_callback", None)
            bot.status_callback = on_status
            try:
                with _chat_lock:  # LLM seri çalışsın
                    reply = bot.process_text(text)
                q.put(("done", reply or ""))
            except Exception as e:
                q.put(("error", str(e)))
            finally:
                bot.status_callback = old_cb

        threading.Thread(target=worker, daemon=True).start()

        while True:
            try:
                kind, val = q.get(timeout=180)
            except queue.Empty:
                self._sse_send({"type": "error", "error": "zaman aşımı"})
                break
            if kind == "status":
                self._sse_send({"type": "status", "text": val})
            elif kind == "error":
                self._sse_send({"type": "error", "error": val})
                break
            else:  # done -> cevabı kademeli gönder
                words, buf = val.split(" "), ""
                for w in words:
                    buf += (w + " ")
                    self._sse_send({"type": "token", "text": w + " "})
                    time.sleep(0.012)
                self._sse_send({"type": "done", "reply": val})
                break

def main():
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    # başlangıçta ısıt (arka planda, server hemen açılsın)
    threading.Thread(target=get_bot, daemon=True).start()
    def _warm_piper():
        try: get_piper()
        except Exception as e: print(f"piper warmup: {e}")
    threading.Thread(target=_warm_piper, daemon=True).start()
    httpd = ThreadingHTTPServer(("", PORT), Handler)  # ÇOKLU THREAD - Failed to fetch fix
    httpd.daemon_threads = True
    print(f"✨ ELİŞA web http://localhost:{PORT} (threading)")
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\ndurdu")

if __name__ == "__main__":
    main()
