# ELİŞA - Hızlı Başlangıç (0₺, Local)

## 1) Test et (30 saniye, kurulum yok)
```bash
cd /Users/arxes/Desktop/ELISHA

# sadece klavye testi (STT/TTS atla)
python3 -m app.cli --mock

# örnekler:
# > Merhaba Elişa
# > Eleşa masaüstünde not.txt oluştur içeriği selam olsun
# > not.txt dosyasını oku
# > masaüstü dosyaları listele
# > saat kaç
# > Chrome'u aç  (macOS'ta dener)
```

## 2) Tam kurulum (macOS)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# ya da minimal:
pip install pyyaml requests sounddevice soundfile webrtcvad numpy scipy pyttsx3 ddgs psutil

# sesli mod (mikrofon gerekli)
python -m app.cli

# desktop UI
python app/desktop.py
```

## 3) Daha akıllı yapmak (opsiyonel, ücretsiz)
```bash
# Ollama indir: https://ollama.com/download
ollama pull qwen2.5:3b   # 2GB, Türkçe iyi
# veya düşük RAM: ollama pull qwen2.5:1.5b

# Piper Türkçe ses (daha doğal ses için, 50MB)
mkdir -p voices
cd voices
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx.json
cd ..
pip install piper-tts

# faster-whisper (offline STT, 150MB-500MB)
pip install faster-whisper
# model otomatik inecek: small (244MB Türkçe için önerilir)
```

## 4) Android APK
```bash
cd android
# Docker (en kolay, Mac'te)
docker run --rm -v "$PWD":/home/user/hostcwd kivy/buildozer -v android debug
# Çıktı: android/bin/elisha-0.1-debug.apk
# Telefona at -> Ayarlar > Bilinmeyen kaynaklara izin ver -> Kur
```

## 5) Wake Word "ELİŞA"
- V1: Buton ("🎙️ Dinle") veya klavye. "Eleşa / Elişa / Elisha" yazman yeterli.
- V2: openWakeWord custom model ("hey elişa") eğitilecek.

## Sorunlar
- `No module named 'faster_whisper'` -> mock modda çalışır, sorun yok. Kurmak istersen `pip install faster-whisper`
- TTS ses yok -> `pip install pyttsx3` (sistem sesi) veya Piper kur
- Ollama yok -> mock mod (kural tabanlı) çalışır, sistem kontrol yine çalışır
- Android build hatası -> Docker kullan, veya Termux ile `pkg install python` sonra `pip install` ile cli çalıştır

## Model boyutları
- faster-whisper tiny: 75MB (hızlı, hatalı)
- small: 244MB (önerilen, Türkçe iyi)
- medium: 769MB (daha iyi, yavaş)
- qwen2.5:1.5b: 1GB
- qwen2.5:3b: 2GB
- Piper tr_TR: 50MB
