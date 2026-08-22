# ELİŞA — Kapsamlı Teknik Özet

> Bu belge, ELİŞA projesini başka bir yapay zekaya tanıtmak için hazırlanmıştır.  
> Tarih: Ağustos 2026 · Versiyon: 0.1.0 · Platform: macOS (arm64)

---

## 1. Proje Nedir?

**ELİŞA**, tamamen yerel çalışan, Türkçe sesli bir kız asistanıdır. JARVIS'in kadın versiyonu olarak tasarlanmıştır. İnternet bağlantısı **gerektirmez** (web araması ve YouTube müzik dışında). Hiçbir API anahtarı yoktur. Tüm AI modelleri cihazda çalışır.

### Temel Özellikler
- **Sesli komutlar**: Mikrofona konuş → STT → LLM → TTS → cevap
- **Wake word**: "hey elişa uyan" deyince uyandırılır (Siri gibi)
- **Sistem kontrolü**: Uygulama aç/kapat, ses seviyesi, ekran görüntüsü, dosya işlemleri
- **Sohbet & akıl yürütme**: qwen2.5:7b ile Türkçe derin sohbet
- **Web araması**: DuckDuckGo ile güncel bilgi
- **Hafıza**: SQLite'da konuşma geçmişi + kullanıcı notları
- **Güvenlik**: Yüksek riskli işlemler (dosya silme) için onay sistemi

---

## 2. Sistem Gereksinimleri

| Bileşen | Minimum | Kurulu |
|---|---|---|
| İşletim sistemi | macOS 12+ | macOS 26.6.1 (arm64) |
| Python | 3.9+ | 3.9.6 (Xcode toolchain) |
| RAM | 8 GB | — |
| Disk (modeller) | ~350 MB | ~350 MB |
| Ollama | 0.3+ | 0.32.15 |
| LLM (minimum) | qwen2.5:1.5b (1.0 GB) | qwen2.5:7b (4.7 GB) + qwen2.5:1.5b |

---

## 3. Proje Yapısı

```
ELISHA/
├── ELİŞA.command          ← macOS çift tık ile başlatıcı
├── config.yaml            ← Tüm ayarlar (LLM, STT, TTS, wake word...)
├── requirements.txt       ← Python bağımlılıkları
├── restart.sh             ← Uygulamayı yeniden başlatır
│
├── app/                   ← Kullanıcı arayüzleri ve sunucu
│   ├── cli.py             ← Terminal CLI (--mock: klavye, varsayılan: sesli)
│   ├── desktop.py         ← Tkinter masaüstü UI (alternatif)
│   ├── desktop_app.py     ← ANA BAŞLATICI: pywebview HUD + süreç yöneticisi
│   ├── server.py          ← HTTP sunucu (port 8765): REST + SSE API
│   ├── wake_daemon.py     ← Arka plan süreci: sürekli "hey elişa" dinler
│   ├── menubar.py         ← macOS menü çubuğu uygulaması (✦ ikonu)
│   └── web/
│       ├── fullscreen.html ← Ana HUD arayüzü (sci-fi, göz animasyonu)
│       ├── index.html      ← Alternatif overlay UI
│       ├── app.js          ← index.html için JS (SSE, mikrofon, wake)
│       └── style.css
│
├── elisha/                ← Çekirdek Python paketi
│   ├── orchestrator.py    ← Merkezi koordinatör (FastPath→Agent→V1 yönlendirme)
│   ├── agent.py           ← V2 native tool-calling agent döngüsü
│   ├── fastpath.py        ← Deterministik regex yönlendirici (LLM'siz, <0.1s)
│   ├── persona_agent.py   ← Agent sistem prompt (ELİŞA kişiliği)
│   ├── persona.py         ← V1 sistem prompt
│   ├── config.py          ← config.yaml yükleyici
│   ├── audio.py           ← VAD+enerji hibrit mikrofon kaydı
│   ├── memory.py          ← SQLite hafıza (konuşmalar + notlar)
│   ├── security.py        ← İzin sistemi (HIGH/CRITICAL onay kapısı)
│   ├── log.py             ← Timestamp+etiket loglayıcı
│   ├── stt/engine.py      ← STT: faster-whisper → whisper → mock
│   ├── tts/engine.py      ← TTS: Piper → pyttsx3 → mock
│   ├── llm/engine.py      ← LLM: Ollama /api/chat → mock kurallar
│   ├── wakeword/detector.py ← Wake word: openWakeWord → STT tabanlı → mock
│   ├── tools/             ← 21 araç (V2 agent + FastPath için)
│   │   ├── system_tools.py  (9 araç: saat, tarih, ses, uygulama, müzik, URL, ekran)
│   │   ├── file_tools.py    (7 araç: listele, oku, oluştur, yaz, kopyala, taşı, sil)
│   │   ├── web_tools.py     (2 araç: web_search, fetch_webpage)
│   │   ├── memory_tools.py  (3 araç: remember, recall, forget)
│   │   ├── shell_tool.py    (1 araç, KAPALI: run_shell)
│   │   ├── base.py          (Tool, ToolResult, RiskLevel sınıfları)
│   │   └── registry.py      (ToolRegistry: Ollama format dönüşümü)
│   └── skills/            ← V1 eski sistem (V2'de yerini tools/ aldı)
│       ├── system.py      (open_app, volume, screenshot, play_music, open_url)
│       └── files.py       (create/read/list/delete — onay sistemi yok!)
│
├── voices/
│   ├── tr_TR-dfki-medium.onnx      ← Piper Türkçe kadın sesi (63 MB)
│   └── tr_TR-dfki-medium.onnx.json ← Ses konfigürasyonu
│
├── data/
│   └── elisha.db          ← SQLite: 160 konuşma satırı, 0 hafıza notu
│
├── scripts/
│   ├── setup_macos.sh     ← Tam kurulum (venv, model, LaunchAgent, .app)
│   └── setup_windows.ps1
│
├── tests/                 ← Unit testler (fastpath, memory, registry, security, shell)
└── android/               ← Kivy tabanlı Android APK (stub, tamamlanmamış)
```

---

## 4. Kurulu Python Bağımlılıkları

### Temel (venv içinde kurulu)

| Paket | Versiyon | Amaç |
|---|---|---|
| `faster-whisper` | 1.2.1 | STT engine (CTranslate2 tabanlı Whisper) |
| `piper-tts` | 1.7.0 | Türkçe TTS (ONNX modeli, offline) |
| `pyttsx3` | 2.99 | TTS yedek (sistem sesi) |
| `sounddevice` | 0.5.6 | Mikrofon kaydı ve ses çalma |
| `soundfile` | 0.13.1 | WAV okuma/yazma |
| `webrtcvad` | 2.0.10 | Ses aktivite tespiti (VAD) |
| `numpy` | 2.0.2 | Ses dizisi işleme |
| `scipy` | 1.13.1 | Ses yeniden örnekleme |
| `requests` | 2.32.5 | Ollama HTTP istemcisi |
| `PyYAML` | 6.0.3 | config.yaml yükleme |
| `ddgs` | 9.8.0 | DuckDuckGo arama |
| `psutil` | 7.2.2 | Sistem bilgisi |
| `rumps` | 0.4.0 | macOS menü çubuğu |
| `pywebview` | 6.2.1 | Native WebKit penceresi |
| `pyobjc` | 11.1 | macOS Objective-C köprüsü |
| `ctranslate2` | 4.8.1 | faster-whisper bağımlılığı |
| `onnxruntime` | 1.19.2 | Piper ONNX çıkarımı |
| `huggingface_hub` | 1.8.0 | Model indirme |
| `av` | 15.1.0 | Ses/video kod çözme |
| `bottle` | 0.13.4 | Mikro web çerçevesi (pywebview) |

### Kurulmayan / Eksik

| Paket | Neden Eksik | Etkisi |
|---|---|---|
| `openwakeword` + `tflite-runtime` | Python 3.9 + macOS arm64'te kurulum başarısız | Wake word STT tabanlı (daha yavaş) |
| `kivy`, `kivymd`, `buildozer` | Sadece Android APK için | Android desteği tamamlanmamış |

---

## 5. Mevcut Konfigürasyon (`config.yaml` özeti)

```yaml
STT:    provider=auto → faster-whisper (small, CPU int8, Türkçe)
TTS:    provider=auto → Piper (tr_TR-dfki-medium) → pyttsx3
LLM:    model=qwen2.5:7b, fallback=qwen2.5:1.5b, temperature=0.5, max_tokens=1500
Agent:  enabled=true, max_steps=8
Audio:  16kHz mono, vad_aggressiveness=2 (kod 1'e kırpıyor), silence_ms=900
Memory: SQLite, 30 mesaj penceresi, session=default
Wake:   "hey elişa uyan" ve 7 varyant
Shell:  run_shell=false (güvenlik)
```

---

## 6. Mimari: Veri Akışı

### Sesli Komut Yolu

```
Mikrofon (16kHz PCM int16)
    │
    ▼
audio.record_until_silence()
    ├─ Enerji < 80  → sessizlik
    ├─ Enerji > 200 → konuşma
    └─ 80-200 arası → webrtcvad VAD kararı
    ├─ 300ms ön-tampon (başlangıç kaybolmasın)
    └─ 900ms sessizlikte dur
    │
    ▼  (sadece wake_daemon.py'de)
WakeWordDetector.detect_stt()
    └─ faster-whisper small (lazy yükleme)
    └─ "hey elişa uyan" varyantı mı? → /tmp/elisha_wake yaz
    │
    ▼  (desktop_app.py 400ms'de poll eder)
Pencere göster → JS: ELISHA_EXTERNAL_WAKE() → micBtn.click()
    │
    ▼
POST /api/listen (server.py)
    └─ _do_listen() → record_until_silence()
    └─ faster-whisper small transkript
       beam_size=5, language=tr, vad_filter=False
       initial_prompt="Türkçe: saat kaç, hava durumu..."
       no_speech_threshold=0.3
    │
    ▼
Metin → POST /api/chat_stream (SSE)
```

### İşleme Yolu

```
ElishaOrchestrator.process_text(metin)
    │
    ├─[1] Bekleyen onay var mı? → evet/hayır yorumla → işle
    │
    ├─[2] FastPath.try_route()           ← Regex, LLM YOK, <0.1s
    │     ├─ Kimlik soruları: "seni kim yaptı" vb.
    │     ├─ Dosya işlemleri, uygulama, ses, tarih/saat
    │     ├─ Müzik, URL, web araması
    │     └─ HIGH risk → NeedConfirmation istisnası
    │
    ├─[3] AgentLoop.run()               ← Ollama native tool-calling
    │     ├─ [sistem_prompt + hafıza_bağlamı + geçmiş(30) + kullanıcı]
    │     ├─ Ollama /api/chat {model, tools, stream=false}
    │     ├─ tool_calls varsa → ToolRegistry.execute() → sonuç ekle → döngü
    │     └─ max_steps=8 sonrası özet
    │
    └─[4] V1 Fallback: LLMEngine.chat() + SkillRegistry
          └─ Ollama /api/chat ([ACTION:] regex) veya mock kurallar
    │
    ▼
_turkish_persona_fix(yanıt)
    ├─ "Ben bir yapay zekayım" → "Ben ELİŞA"
    ├─ siz/size/sizi → sen/sana/seni
    ├─ yapabilirsiniz → yapabilirsin (vb.)
    └─ Çince/garip Unicode → temizle
    │
    ▼
_remember_turn() → SQLite + llm.history (30 mesaj)
```

### Çıktı Yolu

```
Yanıt metni
    ├─ SSE stream (kelime kelime, 12ms gecikme) → tarayıcı chat log
    ├─ _speak_async() → Piper sentez → WAV → afplay (macOS)
    │                 → pyttsx3 yedek
    └─ Chime sesi: "cevap veriyorum" tonu (550Hz→440Hz)
```

### Süreçler Arası İletişim (IPC)

```
/tmp/elisha_wake           ← wake_daemon yazar; desktop_app okur+siler
/tmp/elisha_wake_enabled   ← varlığı = dinleme açık
/tmp/elisha_hide           ← menü çubuğu yazar; desktop_app pencereyi gizler
/tmp/elisha_app.pid        ← tek örnek kilidi
/tmp/elisha_wake_daemon.pid
/tmp/elisha_menubar.pid
```

---

## 7. API Endpoint'leri (port 8765)

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/status` | `{name, stt, tts, llm, wake}` |
| GET | `/api/health` | `{ok: true}` |
| GET | `/api/wake_check` | `/tmp/elisha_wake` kontrol eder |
| POST | `/api/chat` | Senkron sohbet + TTS |
| POST | `/api/chat_stream` | SSE akışı: `status`, `token`, `done`, `error` |
| POST | `/api/listen` | Async mikrofon kaydı başlatır → `{id}` döner |
| POST | `/api/listen/result` | `{id}` ile sonucu poll eder |
| POST | `/api/tts` | Piper ile sentez → base64 WAV |
| POST | `/api/stt` | WebM/WAV → Whisper transkript |
| POST | `/api/wake` | Dışarıdan wake tetikler |
| GET | `/*` | `app/web/` statik dosyaları |

---

## 8. Tüm 21 Araç

### Sistem Araçları (9)

| Araç | Risk | Açıklama |
|---|---|---|
| `get_time` | SAFE | Anlık saat → "Şu an saat HH:MM." |
| `get_date` | SAFE | Türkçe tarih → "Bugün D Ay YYYY, Gün." |
| `get_system_info` | SAFE | İşletim sistemi, Python versiyonu |
| `set_volume` | LOW | up/down/mute/unmute (osascript) |
| `open_application` | LOW | `open -a <uygulama>` (12 takma ad: chrome, vscode vb.) |
| `close_application` | LOW | `pkill -i <isim>` |
| `take_screenshot` | LOW | `screencapture ~/Desktop/elisha-screenshot.png` |
| `play_music` | LOW | YouTube'dan video ID çeker, tarayıcıda açar |
| `open_url` | LOW | `open <url>` |

### Dosya Araçları (7)

| Araç | Risk | Açıklama |
|---|---|---|
| `list_files` | SAFE | Dizin listeler (maks 100, varsayılan ~/Desktop) |
| `read_file` | SAFE | UTF-8 okur, 2000 karakterde kırpar |
| `create_file` | MEDIUM | Oluşturur, üzerine yazar |
| `write_file` | MEDIUM | Ekle modu (dosya yoksa hata) ⚠️ |
| `copy_file` | MEDIUM | shutil.copy2 |
| `move_file` | MEDIUM | shutil.move |
| `delete_file` | **HIGH** | Onay gerektirir, dizin silmeyi reddeder |

### Web Araçları (2)

| Araç | Risk | Açıklama |
|---|---|---|
| `web_search` | SAFE | DuckDuckGo (tr-tr öncelikli, maks 5 sonuç) |
| `fetch_webpage` | SAFE | HTML soyundur, 3000 karakterde kırpar |

### Hafıza Araçları (3)

| Araç | Risk | Açıklama |
|---|---|---|
| `remember` | LOW | SQLite memories tablosuna UPSERT |
| `recall` | SAFE | Anahtar kelime eşleştirme ile hatırla |
| `forget` | MEDIUM | Tam eşleşme → LIKE → sözcük bazlı sil |

### Kabuk Aracı (1, KAPALI)

| Araç | Risk | Açıklama |
|---|---|---|
| `run_shell` | **CRITICAL** | İzin listesi + onay; varsayılan kapalı |

---

## 9. Hafıza Sistemi

```sql
-- conversations tablosu (160 satır mevcut)
id | session_id | role (user/assistant) | content (max 4000 char) | created_at

-- memories tablosu (0 satır mevcut)
id | key | value | category (kisi/proje/tercih/genel) | importance | created_at | updated_at
```

- **Otomatik kayıt**: Her `process_text()` çağrısı user+assistant mesajlarını yazar
- **Oturum geri yükleme**: Başlangıçta son 30 mesaj SQLite'dan `llm.history`'ye yüklenir
- **Bağlam enjeksiyonu**: Agent, memories tablosundaki en önemli 12 notu sistem prompt'una ekler
- **Manuel not**: "bunu hatırla: X" → FastPath → `MemoryStore.remember()`

---

## 10. Çalışan Özellikler ✅

| Özellik | Not |
|---|---|
| Metin sohbeti | CLI mock modu, tüm UI'lar |
| FastPath anlık yönlendirme | <0.1s, LLM gerektirmez |
| Ollama V2 agent (tool calling) | qwen2.5:7b ile |
| Ollama V1 fallback ([ACTION:]) | |
| Mock LLM (çevrimdışı kurallar) | Ollama olmadan 12 komut türü |
| Piper TTS (Türkçe kadın sesi) | tr_TR-dfki-medium, 63MB |
| pyttsx3 TTS yedek | Sistem sesi |
| faster-whisper STT | CPU int8, small model |
| VAD mikrofon kaydı | webrtcvad + enerji hibrit |
| SQLite hafıza | 160 konuşma, oturum geri yükleme |
| HTTP sunucu + SSE | ThreadingHTTP, port 8765 |
| Async mikrofon API | /api/listen + poll |
| 18 çekirdek araç | Sistem, dosya, web |
| 3 hafıza aracı | remember/recall/forget |
| Güvenlik/onay sistemi | HIGH/CRITICAL kapısı |
| macOS uygulama aç/kapat | open -a / pkill |
| macOS ses seviyesi | osascript |
| macOS ekran görüntüsü | screencapture |
| YouTube müzik | Video ID çekme, tarayıcıda aç |
| DuckDuckGo araması | TLS yaması ile |
| Dosya işlemleri | Türkçe yol çözümlemesi |
| Tkinter masaüstü UI | desktop.py |
| pywebview HUD | fullscreen.html |
| macOS menü çubuğu | rumps, ✦ ikonu |
| Ollama otomatik başlatma | Resources binary kullanır |
| Türkçe kişilik düzeltici | siz→sen, yapay zeka→ELİŞA |
| Chime sesleri | Numpy ile üretilen tonlar |
| Tek örnek kilitleri | PID dosyaları |
| Türkçe konuşma & akıl yürütme | max_tokens=1500, geçmiş=30 |

---

## 11. Eksikler ve Bilinen Sorunlar ⚠️

### Kritik Eksikler

| Eksik | Açıklama |
|---|---|
| `openwakeword` kurulu değil | tflite-runtime Python 3.9 + macOS arm64'te kurulmuyor. Wake word STT tabanlı (2.5s döngü, daha yavaş). Özel "hey elişa" modeli eğitilmedi. |
| Android tamamlanmamış | `android/main.py` stub durumunda; mikrofon ve TTS uygulanmamış |
| Windows desteği kısmi | Ses seviyesi çalışmıyor, ekran görüntüsü `mss` gerektiriyor |

### Kod Hataları

| Hata | Konum | Açıklama |
|---|---|---|
| `write_file` yeni dosya oluşturmuyor | `file_tools.py` | Append modu; dosya yoksa hata verir (`create_file` bekleniyor) |
| `vad_aggressiveness` config değeri yoksayılıyor | `audio.py:33` | `min(agg, 1)` ile 1'e kırpılıyor; config'deki 2 etkisiz |
| V1 `FilesSkill.delete()` onaysız | `skills/files.py` | PermissionManager'ı atlar (yalnızca V1 fallback yolunda) |
| `CloseApplicationTool` her zaman başarılı döner | `system_tools.py` | pkill çıkış kodu kontrol edilmiyor |
| LLM geçmişi tekrar riski | `llm/engine.py` | Kullanıcı mesajı hem history'e ekleniyor hem de ayrıca Ollama'ya gönderiliyor |
| `MemoryStore.recall()` verimsiz | `memory.py` | SQL LIKE yerine Python'da 200 satır filtreliyor |
| `config.yaml` wakeword uyumsuzluğu | `config.yaml` | `provider: openwakeword` yazıyor ama kurulu değil |

### Mimari Sınırlamalar

| Sınırlama | Etkisi |
|---|---|
| `_chat_lock` tek LLM kilidi | Eşzamanlı web istekleri sıraya girer |
| `data/elisha.db` göreli yol | Yalnızca proje kökünden başlatılınca çalışır |
| `memories` tablosu hiç kullanılmıyor | 0 satır; `remember` aracı nadiren tetikleniyor |
| `play_music` internet gerektirir | YouTube çekimi; çevrimdışı alternatif yok |
| `fetch_webpage` JS render etmez | SPA sayfaları boş döner |
| `conversations` tablosu büyüyor | Budama mekanizması yok |
| pywebview sürüklenemiyor | `easy_drag=False`; pencere taşınamaz |
| LibreSSL TLS 1.3 yaması kırılgan | ddgs güncellenmesinde yeniden uygulama gerekebilir |

---

## 12. macOS'a Özgü Notlar

| Bileşen | Kullanılan API | Not |
|---|---|---|
| Ses seviyesi | `osascript` (AppleScript) | |
| Ekran görüntüsü | `screencapture` CLI | |
| Uygulama aç | `open -a <AppName>` | /Applications içinde olmalı |
| Uygulama kapat | `pkill -i <name>` | |
| URL aç | `open <url>` | Varsayılan tarayıcı |
| Ses çalma | `afplay` | TTS ve chime'lar için |
| Dock ikonu gizle | `NSBundle + LSUIElement` (pyobjc) | Menü çubuğu uygulaması görünümü |
| Ekran boyutu | `AppKit.NSScreen` (pyobjc) | pywebview tam ekran boyutlandırma |
| Ollama başlatma | `/Applications/Ollama.app/Contents/Resources/ollama start` | GUI sarmalayıcı çöküyor; direkt binary kullanılıyor |
| LaunchAgents | `~/Library/LaunchAgents/com.elisha.*.plist` | `setup_macos.sh` ile kurulur |
| Python sürümü | Xcode araç zinciri 3.9.6 | tflite-runtime kurulumu engelleniyor |
| LibreSSL | 2.8.3 (TLS 1.3 yok) | `_patch_ddgs_tls()` ile geçici çözüm uygulandı |

---

## 13. Çalışma Zamanı Durumu

### Aktif Süreçler (uygulama çalışırken)

| Süreç | Dosya | Görev |
|---|---|---|
| `desktop_app.py` | PID: `/tmp/elisha_app.pid` | Ana süreç: pywebview, HTTP sunucu, poll döngüsü |
| `server.py` | port 8765 | Arka plan thread; desktop_app içinden başlatılıyor |
| `wake_daemon.py` | PID: `/tmp/elisha_wake_daemon.pid` | Her 2.5s mikrofon dinler, wake word bekler |
| `menubar.py` | PID: `/tmp/elisha_menubar.pid` | macOS menü çubuğu ikonu |

### Veritabanı Durumu (anlık)

| Tablo | Satır Sayısı |
|---|---|
| conversations | 160 |
| memories | 0 |

### Yüklü Ollama Modelleri

| Model | Boyut | Kullanım |
|---|---|---|
| qwen2.5:7b | 4.7 GB | Birincil LLM (akıllı mod) |
| qwen2.5:1.5b | 1.0 GB | Yedek LLM |

### Ses Modelleri

| Model | Boyut | Yol |
|---|---|---|
| Piper tr_TR-dfki-medium | 63 MB | `voices/tr_TR-dfki-medium.onnx` |
| Whisper small (faster-whisper) | ~244 MB | HuggingFace cache |

---

## 14. Nasıl Başlatılır?

### Tam uygulama (GUI, önerilen)
```bash
# Terminal açmadan: ELİŞA.command dosyasına çift tıkla
# VEYA:
cd /Users/arxes/Desktop/ELISHA
source venv/bin/activate
python3 app/desktop_app.py
```

### Sadece terminal (yazarak test)
```bash
source venv/bin/activate
python3 -m app.cli --mock
```

### Sesli CLI
```bash
source venv/bin/activate
python3 -m app.cli
```

### Yeniden başlatma
```bash
bash restart.sh && open "ELİŞA.command"
```

---

## 15. İstatistikler

| Metrik | Değer |
|---|---|
| Toplam Python kaynak dosyası | ~35 |
| Yaklaşık kod satırı (HTML/CSS hariç) | ~3.200 |
| fullscreen.html satır sayısı | ~1.441 |
| Çalışma anında kayıtlı araç | 21 |
| Kurulu pip paketi | ~65 (+100 pyobjc) |
| Desteklenen LLM sağlayıcısı | 2 (Ollama, mock) |
| Desteklenen STT sağlayıcısı | 3 (faster-whisper, whisper, mock) |
| Desteklenen TTS sağlayıcısı | 3 (Piper, pyttsx3, mock) |
| Çalışma anında aktif süreç | 4 |
| IPC mekanizması | /tmp/ dosya bayrakları |
| Veritabanı | SQLite 3 |
| Ses modeli | Piper tr_TR-dfki-medium (DFKI, 22050Hz) |
| STT modeli | faster-whisper small (244MB, int8 CPU) |
| LLM (birincil) | qwen2.5:7b (4.7GB, Q4_K_M) |

---

## 16. Sonraki Adımlar / Öneriler

Öncelik sırasına göre yapılabilecekler:

1. **OpenWakeWord Python 3.10+ ile** — Python sürümünü yükseltip custom "hey elişa" modeli eğitmek, STT tabanlı wake yerine gerçek arka plan dinlemesi sağlar
2. **`write_file` düzeltmesi** — Dosya yoksa oluşturulmalı (create_file ile aynı davranış)
3. **Memories tablosunu kullanma** — Agent'ın kullanıcı tercihlerini otomatik kaydetmesi (isim, proje, tercihler)
4. **`conversations` tablosu budama** — Örn. son 500 satır koru, eskisini sil
5. **Piper daha iyi ses modeli** — `tr_TR-fahrettin-medium` denenmesi (farklı erkek sesi seçeneği)
6. **Android tamamlama** — Kivy mikrofon + TTS entegrasyonu
7. **Windows ses seviyesi** — `pycaw` kütüphanesi ile
8. **LibreSSL yamasını kalıcı hale getirme** — venv kurulumundan sonra otomatik uygulanan post-install scripti

---

*Bu belge, konuşma geçmişi ve kaynak kodu analizi ile otomatik olarak oluşturulmuştur.*  
*Son güncelleme: 22 Ağustos 2026*
