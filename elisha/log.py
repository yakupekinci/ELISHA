"""AŞAMA 22 — Kategorize loglama.

Etiketler: STT | WAKE | LLM | AGENT | TOOL | SECURITY | MEMORY | TTS |
           FASTPATH | CHAT | SERVER | ERROR
Çıktı örneği: [19:52:01] [TOOL] 📁 list_files -> ok (0.21s)
"""
import sys
import threading
import time

_lock = threading.Lock()

QUIET = False  # testlerde kapatmak için


def log(tag: str, msg: str) -> None:
    if QUIET:
        return
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{tag}] {msg}"
    with _lock:
        try:
            print(line, flush=True)
        except Exception:
            # bozuk pipe vs. durumunda sessiz geç
            try:
                sys.stderr.write(line + "\n")
            except Exception:
                pass


def err(msg: str) -> None:
    log("ERROR", msg)
