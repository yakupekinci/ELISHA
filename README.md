# ELİŞA — Sesli Asistan (JARVIS benzeri, %100 Local, Ücretsiz)

**Türkçe okunuş: "Eliyşşa"** — Tamamen offline, ücretsiz, cross-platform sesli asistan.

> Para verme. Buluta gitme. Her şey cihazında çalışsın.

## Özellikler (V1 - MVP)
- 🎤 **STT**: `faster-whisper` (offline) → `whisper.cpp` fallback
- 🧠 **LLM**: Ollama (`qwen2.5:3b` / `llama3.2:3b` önerilen) → yoksa kural tabanlı offline mod
- 🔊 **TTS**: `Piper TTS` (tr_TR sesi, offline, ~50MB) → `pyttsx3` sistem sesi fallback
- 👂 **Wake Word**: `openWakeWord` ("hey elişa" / "elişa") → yoksa Buton / Klavye tetik
- 🖥️ **Sistem Kontrol**: Uygulama aç/kapa, dosya işlemleri, shell komut, ses/parlaklık, web araması (DuckDuckGo, ücretsiz)
- 📱 **Cross-Platform**: macOS + Windows (Python desktop app) + **Android APK** (Kivy + Buildozer)
- 🇹🇷 **Türkçe**: Tam Türkçe STT/TTS, ELİŞA persona

## Hızlı Başlat (macOS / Windows - 3 adım)

### 1. Python sanal ortam
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Modeller (opsiyonel ama önerilen - tamamen ücretsiz)
```bash
# Piper Türkçe ses (50MB)
python -m elisha.tts.engine --download tr_TR

# Ollama + model (en iyi kalite için, yoksa kural tabanlı çalışır)
# https://ollama.com/download -> kur, sonra:
ollama pull qwen2.5:3b
# veya: ollama pull llama3.2:3b
# Düşük RAM için: ollama pull qwen2.5:1.5b
```

### 3. Çalıştır
```bash
# CLI (mikrofon -> ELİŞA -> hoparlör)
python -m app.cli

# Desktop UI (macOS/Win)
python app/desktop.py

# Sadece test (mikrofon/TTS olmadan)
python -m app.cli --mock
```

## Android APK Oluşturma

### Seçenek A: Buildozer (macOS/Linux'ta, Docker ile en kolay)
```bash
cd android
# Docker ile (önerilen, NDK/SDK otomatik)
docker run --rm -v "$PWD":/home/user/hostcwd kivy/buildozer -v android debug
# Çıktı: bin/elisha-0.1-debug.apk -> telefona at, kur
```

### Seçenek B: Doğrudan Buildozer (Linux)
```bash
pip install buildozer cython
cd android
buildozer android debug
```

> Android'de tam offline için: Whisper tiny/base + Qwen 1.5B (GGUF) + Piper tr_TR ~2-3GB yer kaplar. 6GB RAM altı cihazlarda sadece STT+TTS + hibrit (evdeki PC'de Ollama) önerilir.

## Mimari
```
Mikrofon -> VAD (webrtcvad) -> faster-whisper (STT) -> ELİŞA Orchestrator -> LLM (Ollama) -> Skills -> Piper TTS -> Hoparlör
                \-> Wake Word ("elişa") ile tetiklenir
```

## Yapılandırma
`config.yaml` dosyasını düzenle:
```yaml
language: tr
wake_word: "elişa"
stt:
  model: small   # tiny/base/small/medium
  language: tr
tts:
  provider: piper
  voice: tr_TR-dfki-medium  # veya tr_TR-fahrettin
llm:
  provider: ollama  # ollama | mock
  model: qwen2.5:3b
```

## Sistem Kontrol Örnekleri
- "Eleşa, Chrome'u aç"
- "Eleşa, ekran görüntüsü al"
- "Eleşa, masaüstünde not.txt oluştur içeriği merhaba olsun"
- "Eleşa, sesi kıs"
- "Eleşa, hava durumu Ankara" (DuckDuckGo)

## Klasör Yapısı
```
elisha/          # çekirdek paket (STT/TTS/LLM/skills)
app/             # desktop + cli arayüzleri
android/         # Kivy APK projesi
scripts/         # kurulum scriptleri
voices/          # Piper ses modelleri (indirilince)
```

## Lisans
MIT — İstediğin gibi değiştir, dağıt.

## Notlar
- İnternet yokken bile çalışır (Ollama + Piper + Whisper local ise).
- İlk kurulumda internet gerekir (model indirmek için) — sonrası tamamen offline.
- Bütçe: 0₺. Tüm bileşenler açık kaynak.

---
Yapıldı: Muse Spark 1.2 Free (High) ile — ELİŞA V1

---
## 🔐 Yeni Makinede Kurulum

```bash
# 1) Anahtarları şifreli yedekten geri yükle (parola repo'da YOK — sahibinde)
./scripts/secrets.sh restore

# 2) Türkçe Piper sesini indir (~60MB)
mkdir -p voices && cd voices
curl -L -o tr_TR-dfki-medium.onnx \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx"
curl -L -o tr_TR-dfki-medium.onnx.json \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx.json"

# 3) Başlat
./ELİŞA.command
```

Şablon: `config/secrets.env.example` • Şifreli paket: `config/secrets.env.enc` (AES-256-CBC + PBKDF2)

## ✨ Son Sürüm Özellikleri (V2 "Tam Yardımcı")
- 🔴 **Gemini Live** gerçek zamanlı ses (<1sn, "hey elişa" → canlı sohbet, "kapat kendini" ile biter)
- 🧠 **40 araç**: sistem kontrolü, medya, uygulamalar, YouTube arama+oynatma, uçuş, oyun güncelleyici, WhatsApp/Telegram mesaj hazırlama, PDF, ekran+kamera görüşü
- 📱 **QR Uzaktan Kumanda** (telefondan, token korumalı LAN sunucusu)
- 📋 **Pano Zekası** (kopyala → Çevir/Özetle/Açıkla/Düzelt çipleri)
- 📊 **Donanım izleme** (fansız MacBook için sesli ısı uyarısı) + **otomatik başlatma**
- 🌅 Sabah brifingi (dünkü konuları hatırlar) + 🔔 haber takibi + 🧩 eklenti sistemi
- 🇹🇷 Hibrit Türkçe wake word (enerji segmentasyonu + whisper doğrulama)
