"""
ELİŞA — Kız Asistan (düzeltildi, macOS uyumlu)
Basit, sağlam, koyu tema. Çalıştır: python app/desktop.py
"""
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import tkinter as tk
from tkinter import scrolledtext

from elisha.orchestrator import ElishaOrchestrator

BG = "#0f0f1a"
CARD = "#1a1a2e"
INPUT_BG = "#25254a"
PINK = "#ff2e97"
PURPLE = "#a855f7"
WHITE = "#f5f5ff"
GRAY = "#9aa0b0"

class ElisaUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ELİŞA — kız asistan")
        self.root.geometry("880x680")
        self.root.minsize(760, 560)
        self.root.configure(bg=BG)
        self.bot = None
        self.listening = False
        self.wake_on = False
        self._build()
        self._init_bot()
        self.root.after(1000, self._poll_external_wake)

    def _build(self):
        # ÜST BAR
        top = tk.Frame(self.root, bg=CARD, height=62)
        top.pack(fill=tk.X, side=tk.TOP)
        top.pack_propagate(False)
        tk.Label(top, text="  ELİŞA", bg=CARD, fg=WHITE, font=("Helvetica", 20, "bold")).pack(side=tk.LEFT, padx=12, pady=10)
        tk.Label(top, text="Eliyşşa  •  kız  •  Türkçe  •  local", bg=CARD, fg="#c9b3ff", font=("Helvetica", 10)).pack(side=tk.LEFT, pady=14)
        self.status_dot = tk.Label(top, text="● hazırlanıyor", bg=CARD, fg=GRAY, font=("Helvetica", 9))
        self.status_dot.pack(side=tk.RIGHT, padx=14)

        # ORTA: chat
        mid = tk.Frame(self.root, bg=BG)
        mid.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # avatar satırı (basit, emoji)
        avatar_row = tk.Frame(mid, bg=BG, height=110)
        avatar_row.pack(fill=tk.X, pady=(0,8))
        avatar_row.pack_propagate(False)
        # sol avatar
        av = tk.Frame(avatar_row, bg=CARD, width=90, height=90)
        av.pack(side=tk.LEFT, padx=6, pady=6)
        av.pack_propagate(False)
        tk.Label(av, text="💫", bg=CARD, fg=PINK, font=("Helvetica", 36)).pack(expand=True)
        tk.Label(av, text="ELİŞA", bg=CARD, fg=WHITE, font=("Helvetica", 8, "bold")).pack(side=tk.BOTTOM, pady=2)
        # sağ bilgi
        info = tk.Frame(avatar_row, bg=CARD)
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8,0))
        tk.Label(info, text="JARVIS'in kız hali — sıcak, zeki, zarif", bg=CARD, fg=WHITE, font=("Helvetica", 11, "bold"), anchor="w").pack(fill=tk.X, padx=12, pady=(12,2))
        tk.Label(info, text="Piper kız sesi • Whisper Türkçe • Ollama local", bg=CARD, fg=GRAY, font=("Helvetica", 9), anchor="w").pack(fill=tk.X, padx=12)
        self.badge = tk.Label(info, text="STT • TTS • LLM yükleniyor...", bg=INPUT_BG, fg=GRAY, font=("Helvetica", 8), anchor="w", padx=8, pady=4)
        self.badge.pack(fill=tk.X, padx=12, pady=8)

        # chat kutusu - Text + Scrollbar (manuel, macOS'ta daha sağlam)
        chat_frame = tk.Frame(mid, bg=CARD, bd=1, relief=tk.FLAT, highlightbackground="#2a2a4a", highlightthickness=1)
        chat_frame.pack(fill=tk.BOTH, expand=True)

        # başlık
        hdr = tk.Frame(chat_frame, bg="#1e1e3a", height=28)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  Sohbet", bg="#1e1e3a", fg=WHITE, font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=8, pady=4)
        self.cnt_label = tk.Label(hdr, text="0 mesaj", bg="#1e1e3a", fg=GRAY, font=("Helvetica", 8))
        self.cnt_label.pack(side=tk.RIGHT, padx=8)

        # Text ve scrollbar
        text_wrap = tk.Frame(chat_frame, bg=CARD)
        text_wrap.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.chat = tk.Text(text_wrap, wrap=tk.WORD, font=("Helvetica", 11), bg=CARD, fg=WHITE,
                            insertbackground=PINK, relief=tk.FLAT, bd=0, padx=12, pady=10,
                            selectbackground=PURPLE, selectforeground=WHITE, state=tk.DISABLED, highlightthickness=0)
        sb = tk.Scrollbar(text_wrap, command=self.chat.yview, bg=CARD, troughcolor=CARD, activebackground=PURPLE, width=8, bd=0)
        self.chat.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat.tag_config("user", foreground="#f0abfc", font=("Helvetica", 10, "bold"))
        self.chat.tag_config("usermsg", foreground=WHITE, font=("Helvetica", 11))
        self.chat.tag_config("bot", foreground=PINK, font=("Helvetica", 10, "bold"))
        self.chat.tag_config("botmsg", foreground="#e8e8ff", font=("Helvetica", 11))
        self.chat.tag_config("sys", foreground=GRAY, font=("Helvetica", 9, "italic"), justify=tk.CENTER)

        # ALT BAR
        bottom = tk.Frame(self.root, bg=BG, height=110)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, padx=12, pady=10)
        bottom.pack_propagate(False)

        # input satırı
        inp_row = tk.Frame(bottom, bg=INPUT_BG, height=42, bd=1, relief=tk.FLAT, highlightbackground="#3a3a6a", highlightthickness=1)
        inp_row.pack(fill=tk.X, pady=(0,8))
        inp_row.pack_propagate(False)
        self.entry = tk.Entry(inp_row, font=("Helvetica", 12), bg=INPUT_BG, fg=WHITE, insertbackground=PINK, bd=0, relief=tk.FLAT)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=8)
        self.entry.bind("<Return>", lambda e: self.send())
        # placeholder
        self.entry.insert(0, "ELİŞA'ya yaz...")
        self.entry.config(fg=GRAY)
        def on_in(e):
            if self.entry.get() == "ELİŞA'ya yaz...":
                self.entry.delete(0, tk.END); self.entry.config(fg=WHITE)
        def on_out(e):
            if not self.entry.get().strip():
                self.entry.insert(0, "ELİŞA'ya yaz..."); self.entry.config(fg=GRAY)
        self.entry.bind("<FocusIn>", on_in)
        self.entry.bind("<FocusOut>", on_out)

        send = tk.Button(inp_row, text="Gönder ✦", bg=PINK, fg=WHITE, activebackground=PURPLE, activeforeground=WHITE,
                         font=("Helvetica", 11, "bold"), bd=0, padx=14, pady=4, cursor="hand2", command=self.send)
        send.pack(side=tk.RIGHT, padx=6, pady=6)

        # buton satırı
        btn_row = tk.Frame(bottom, bg=BG)
        btn_row.pack(fill=tk.X)
        self.mic_btn = tk.Button(btn_row, text="🎙️  Dinle", bg=CARD, fg=WHITE, activebackground="#2a1a3a", font=("Helvetica", 10, "bold"),
                                 bd=1, relief=tk.FLAT, highlightbackground="#3a3a6a", highlightthickness=1, padx=14, pady=6, cursor="hand2", command=self.listen)
        self.mic_btn.pack(side=tk.LEFT, padx=(0,6))
        self.wake_btn = tk.Button(btn_row, text="✨ Hey ELİŞA kapalı", bg=CARD, fg=GRAY, activebackground="#2a1a3a", font=("Helvetica", 10, "bold"),
                                  bd=1, relief=tk.FLAT, highlightbackground="#3a3a6a", highlightthickness=1, padx=12, pady=6, cursor="hand2", command=self.toggle_wake)
        self.wake_btn.pack(side=tk.LEFT)
        self.hint = tk.Label(btn_row, text="Hazırlanıyor...", bg=BG, fg=GRAY, font=("Helvetica", 8))
        self.hint.pack(side=tk.RIGHT)

    def _init_bot(self):
        def load():
            self.log_sys("ELİŞA uyanıyor...")
            try:
                self.bot = ElishaOrchestrator()
                prov = f"STT:{self.bot.stt.provider}  TTS:{self.bot.tts.provider}  LLM:{self.bot.llm.provider}"
                self.status_dot.config(text=f"● {prov}", fg="#22c55e")
                self.badge.config(text=prov, fg="#a7f3d0")
                self.hint.config(text="Hazır")
                self.log_bot("Merhaba, ben ELİŞA ✨ — kız asistanın. Yaz veya 🎙️ Dinle, ya da Hey ELİŞA de.")
            except Exception as e:
                self.status_dot.config(text=f"● hata: {e}", fg="#ef4444")
                self.log_sys(f"Hata: {e}")
        threading.Thread(target=load, daemon=True).start()

    def log_user(self, t):
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"\nSEN — {time.strftime('%H:%M')}\n", "user")
        self.chat.insert(tk.END, f"{t}\n", "usermsg")
        self.chat.config(state=tk.DISABLED); self.chat.see(tk.END); self._cnt()

    def log_bot(self, t):
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"\nELİŞA — {time.strftime('%H:%M')}\n", "bot")
        for line in t.split("\n"):
            if line.strip(): self.chat.insert(tk.END, f"{line}\n", "botmsg")
        self.chat.config(state=tk.DISABLED); self.chat.see(tk.END); self._cnt()

    def log_sys(self, t):
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"\n— {t} —\n", "sys")
        self.chat.config(state=tk.DISABLED); self.chat.see(tk.END)

    def _cnt(self):
        txt = self.chat.get("1.0", tk.END)
        c = txt.count("SEN —") + txt.count("ELİŞA —")
        self.cnt_label.config(text=f"{c} mesaj")

    def send(self):
        if not self.bot:
            self.log_sys("ELİŞA henüz hazır değil"); return
        t = self.entry.get().strip()
        if not t or t == "ELİŞA'ya yaz...": return
        self.entry.delete(0, tk.END)
        self.log_user(t)
        self.hint.config(text="ELİŞA düşünüyor...")
        def work():
            try:
                r = self.bot.process_text(t)
                self.root.after(0, lambda: self.log_bot(r))
                self.root.after(0, lambda: self.hint.config(text="Hazır"))
                if self.bot.config.get("assistant", {}).get("voice_response"):
                    try: self.bot.speak(r)
                    except Exception as e: self.root.after(0, lambda: self.log_sys(f"Ses: {e}"))
            except Exception as e:
                self.root.after(0, lambda: self.log_sys(f"Hata: {e}"))
                self.root.after(0, lambda: self.hint.config(text="Hata"))
        threading.Thread(target=work, daemon=True).start()

    def listen(self):
        if not self.bot or self.listening: return
        self.listening = True
        self.mic_btn.config(text="⏹ Durdur", bg=PINK, fg=WHITE)
        self.hint.config(text="Dinliyorum... konuş")
        self.log_sys("🎙️ Dinliyorum... sessizlikte duracak")
        def do():
            try:
                txt = self.bot.listen_once()
                if not txt and self.bot.stt.provider=="mock":
                    self.root.after(0, lambda: self.log_sys("STT mock — yazarak dene"))
                elif txt:
                    self.root.after(0, lambda: self.log_user(f"(ses) {txt}"))
                    r = self.bot.process_text(txt)
                    self.root.after(0, lambda: self.log_bot(r))
                    try: self.bot.speak(r)
                    except: pass
                else:
                    self.root.after(0, lambda: self.log_sys("Ses yok"))
            except Exception as e:
                self.root.after(0, lambda: self.log_sys(f"Dinleme: {e}"))
            finally:
                self.listening=False
                self.root.after(0, lambda: self.mic_btn.config(text="🎙️  Dinle", bg=CARD, fg=WHITE))
                self.root.after(0, lambda: self.hint.config(text="Hazır"))
        threading.Thread(target=do, daemon=True).start()

    def toggle_wake(self):
        if not self.bot:
            self.log_sys("ELİŞA hazır değil"); return
        self.wake_on = not self.wake_on
        # daemon ile senkron için flag dosyası
        flag = Path("/tmp/elisha_wake_enabled")
        if self.wake_on:
            self.wake_btn.config(text="✨ Hey ELİŞA açık", bg=PINK, fg=WHITE)
            self.hint.config(text="Hey ELİŞA bekleniyor... sadece 'hey elişa uyan' ile uyanırım")
            self.log_sys("✨ Hey ELİŞA açık — sadece 'hey elişa uyan' deyince uyanacağım, sürekli komut beklemiyorum")
            try: flag.write_text("1")
            except: pass
            # uygulama içi wake artık daemon'a bırakıldı, burada ek thread başlatma yok (çift mikrofon çakışması önlenir)
        else:
            self.wake_btn.config(text="✨ Hey ELİŞA kapalı", bg=CARD, fg=GRAY)
            self.hint.config(text="Hazır — uyuyor")
            self.log_sys("Hey ELİŞA uyuyor — 'hey elişa uyan' demeden kalkmam")
            try: flag.unlink(missing_ok=True)
            except: pass

    def _poll_external_wake(self):
        """Daemon'dan gelen /tmp/elisha_wake dosyasını poll et (Siri gibi sistem geneli)"""
        try:
            p = Path("/tmp/elisha_wake")
            if p.exists():
                txt = p.read_text().strip()
                p.unlink()
                self.log_sys(f"✨ Dış Hey ELİŞA: '{txt}' — uyanıyorum")
                self._on_wake_triggered()
        except: pass
        self.root.after(700, self._poll_external_wake)

    def _wake_loop(self):
        import numpy as np
        try:
            import sounddevice as sd
        except Exception as e:
            self.root.after(0, lambda: self.log_sys(f"Wake: {e}")); return
        print("wake loop start")
        while self.wake_on:
            if self.listening:
                time.sleep(0.4); continue
            try:
                sr=16000; dur=1.8
                rec=sd.rec(int(dur*sr), samplerate=sr, channels=1, dtype='int16')
                sd.wait()
                audio=rec.flatten()
                if np.abs(audio).mean() < 180:
                    time.sleep(0.2); continue
                trig, txt = self.bot.wakeword.detect_stt(audio, sr)
                if trig:
                    self.root.after(0, lambda: self.log_sys(f"✨ Hey ELİŞA duydum: {txt}"))
                    self.root.after(0, lambda: self.hint.config(text="Hey ELİŞA! Dinliyorum..."))
                    try: self.bot.speak("Buyurun, sizi dinliyorum")
                    except: pass
                    self.root.after(700, self.listen)
                    time.sleep(3.2)
                else:
                    time.sleep(0.25)
            except Exception as e:
                print("wake err", e); time.sleep(0.6)
        print("wake loop stop")

def main():
    root = tk.Tk()
    # macOS'ta koyu mod için
    try: root.tk.call('tk', 'scaling', 1.2)
    except: pass
    ElisaUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
