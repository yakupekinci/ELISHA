#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║  ELİŞA — macOS Kurulum & Yeniden Kurulum Scripti         ║
# ║  Reset sonrası veya ilk kurulum için çalıştır            ║
# ╚══════════════════════════════════════════════════════════╝
set -e

ELISHA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON=$(command -v python3 || echo "/usr/bin/python3")
USER_NAME=$(whoami)

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  ELİŞA Kurulum Başlıyor              ║"
echo "║  Dizin: $ELISHA_ROOT"
echo "║  Kullanıcı: $USER_NAME"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Çalıştırma izinleri ────────────────────────────────────────────────
echo "1/6 Çalıştırma izinleri ayarlanıyor..."
chmod +x "$ELISHA_ROOT/ELİŞA.command"
# macOS quarantine kaldır (Gatekeeper engeli)
xattr -d com.apple.quarantine "$ELISHA_ROOT/ELİŞA.command" 2>/dev/null || true
echo "   ✅ ELİŞA.command çalıştırılabilir"

# ── 2. Python bağımlılıkları ──────────────────────────────────────────────
echo ""
echo "2/6 Python bağımlılıkları kuruluyor..."
cd "$ELISHA_ROOT"

# Venv oluştur (yoksa)
if [ ! -d "venv" ]; then
    echo "   Sanal ortam oluşturuluyor..."
    $PYTHON -m venv venv
fi
source "$ELISHA_ROOT/venv/bin/activate"
PYTHON="$ELISHA_ROOT/venv/bin/python3"
PIP="$ELISHA_ROOT/venv/bin/pip"

$PIP install --upgrade pip --quiet
$PIP install -r requirements.txt --quiet
echo "   ✅ Bağımlılıklar kuruldu"

# ── 3. Piper ses modeli ───────────────────────────────────────────────────
echo ""
echo "3/6 Piper Türkçe ses modeli kontrol ediliyor..."
mkdir -p "$ELISHA_ROOT/voices"
PIPER_ONNX="$ELISHA_ROOT/voices/tr_TR-dfki-medium.onnx"
PIPER_JSON="$ELISHA_ROOT/voices/tr_TR-dfki-medium.onnx.json"
BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium"

if [ ! -f "$PIPER_ONNX" ]; then
    echo "   İndiriliyor (~63MB)..."
    curl -L --progress-bar -o "$PIPER_ONNX" "$BASE_URL/tr_TR-dfki-medium.onnx"
    curl -L --progress-bar -o "$PIPER_JSON" "$BASE_URL/tr_TR-dfki-medium.onnx.json"
    echo "   ✅ Piper sesi indirildi"
else
    echo "   ✅ Piper sesi zaten mevcut"
fi

# ── 4. Ollama ve model ────────────────────────────────────────────────────
echo ""
echo "4/6 Ollama ve LLM modeli kontrol ediliyor..."

if command -v ollama &> /dev/null; then
    echo "   ✅ Ollama bulundu"
    # Model var mı?
    if ollama list 2>/dev/null | grep -q "qwen2.5:7b"; then
        echo "   ✅ qwen2.5:7b zaten var"
    elif ollama list 2>/dev/null | grep -q "qwen2.5:3b"; then
        echo "   ✅ qwen2.5:3b zaten var"
    else
        echo "   Model indiriliyor qwen2.5:3b (~2GB)..."
        ollama pull qwen2.5:3b || echo "   ⚠️  Model indirilemedi, sonra dene: ollama pull qwen2.5:3b"
    fi
else
    echo "   ⚠️  Ollama bulunamadı!"
    echo "   İndirmek için: https://ollama.com/download"
    echo "   Sonra çalıştır: ollama pull qwen2.5:3b"
fi

# ── 5. LaunchAgents (otomatik başlatma) ───────────────────────────────────
echo ""
echo "5/6 Otomatik başlatma ayarlanıyor..."
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

# Eski plist'leri kaldır (hardcoded path olabilir)
launchctl unload "$LAUNCH_DIR/com.elisha.autostart.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_DIR/com.elisha.wake.plist" 2>/dev/null || true

# Güncel plist oluştur (dinamik path)
cat > "$LAUNCH_DIR/com.elisha.autostart.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.elisha.autostart</string>
    <key>ProgramArguments</key>
    <array>
        <string>$ELISHA_ROOT/ELİŞA.command</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/elisha-autostart.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/elisha-autostart.log</string>
    <key>WorkingDirectory</key>
    <string>$ELISHA_ROOT</string>
</dict>
</plist>
EOF

cat > "$LAUNCH_DIR/com.elisha.wake.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.elisha.wake</string>
    <key>ProgramArguments</key>
    <array>
        <string>$ELISHA_ROOT/venv/bin/python3</string>
        <string>-u</string>
        <string>$ELISHA_ROOT/app/wake_daemon.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/wake.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/wake.log</string>
    <key>WorkingDirectory</key>
    <string>$ELISHA_ROOT</string>
</dict>
</plist>
EOF

# Yükle
launchctl load "$LAUNCH_DIR/com.elisha.autostart.plist" 2>/dev/null && \
    echo "   ✅ Otomatik başlatma (login) aktif" || \
    echo "   ⚠️  LaunchAgent yüklenemedi (macOS izin gerekebilir)"

launchctl load "$LAUNCH_DIR/com.elisha.wake.plist" 2>/dev/null && \
    echo "   ✅ Wake daemon (arka plan) aktif" || \
    echo "   ⚠️  Wake daemon yüklenemedi"

# ── 6. Dock kısayolu ──────────────────────────────────────────────────────
echo ""
echo "6/6 Dock ve Finder kısayolları..."

# .command dosyasını Dock'a eklemeye yardımcı olacak bir .app wrapper
APP_DIR="$ELISHA_ROOT/ELİŞA.app"
# Her zaman yeniden oluştur (güncelleme için)
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# Info.plist — Dock'ta düzgün görünmesi için gerekli tüm key'ler
cat > "$APP_DIR/Contents/Info.plist" << EOF2
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>elisha_launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.elisha.voiceassistant</string>
    <key>CFBundleName</key>
    <string>ELİŞA</string>
    <key>CFBundleDisplayName</key>
    <string>ELİŞA</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>4.0</string>
    <key>CFBundleShortVersionString</key>
    <string>4.0</string>
    <key>CFBundleIconFile</key>
    <string>elisha_icon</string>
    <key>CFBundleIconName</key>
    <string>elisha_icon</string>
    <key>LSUIElement</key>
    <false/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>ELİŞA sesli komutları dinlemek için mikrofona ihtiyaç duyar.</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
</dict>
</plist>
EOF2

# Launcher script — repodaki kanonik sürümü kopyala (tek doğruluk kaynağı)
cp "$ELISHA_ROOT/app/elisha_launcher" "$APP_DIR/Contents/MacOS/elisha_launcher"
chmod +x "$APP_DIR/Contents/MacOS/elisha_launcher"

# İkon kopyala (icns > png tercih et)
if [ -f "$ELISHA_ROOT/app/elisha_icon.icns" ]; then
    cp "$ELISHA_ROOT/app/elisha_icon.icns" "$APP_DIR/Contents/Resources/elisha_icon.icns"
elif [ -f "$ELISHA_ROOT/app/elisha_icon.png" ]; then
    cp "$ELISHA_ROOT/app/elisha_icon.png" "$APP_DIR/Contents/Resources/elisha_icon.png"
fi

# PkgInfo dosyası (Finder hız optimizasyonu)
echo -n "APPL????" > "$APP_DIR/Contents/PkgInfo"

# Finder'a uygulama olarak tanıt
touch "$APP_DIR"
echo "   ✅ ELİŞA.app oluşturuldu (Dock'a sürüklenebilir)"

# Quarantine kaldır
xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true
xattr -d com.apple.quarantine "$ELISHA_ROOT/ELİŞA.command" 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅ KURULUM TAMAMLANDI!                               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                       ║"
echo "║  Başlatmak için:                                      ║"
echo "║  1. ELİŞA.app'e çift tıkla (Dock'a sürükle)          ║"
echo "║  veya:                                                ║"
echo "║  2. ELİŞA.command'a çift tıkla                        ║"
echo "║                                                       ║"
echo "║  Sonraki açılışta otomatik başlayacak (LoginItem)     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
