#!/bin/bash
# ELİŞA başlatıcı — tek giriş noktası
# Hardcoded path YOK — nerede olursa olsun çalışır

# Çalışma dizinini projenin köküne al
cd "$(dirname "$0")"
ELISHA_ROOT="$(pwd)"

# Python PATH'i genişlet (Homebrew, local, venv)
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# ── API anahtarlarını yükle (güvenli: kaynak koda yazılmaz) ────────────────
SECRETS="$HOME/.config/elisha/secrets.env"
if [ -f "$SECRETS" ]; then
    set -a
    source "$SECRETS"
    set +a
fi

# Venv varsa aktif et
if [ -f "$ELISHA_ROOT/venv/bin/activate" ]; then
    source "$ELISHA_ROOT/venv/bin/activate"
fi

# ── Ollama başlat ──────────────────────────────────────────────────────────
echo "⚙️  Ollama kontrol ediliyor..."

if curl -s --max-time 1 http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama zaten çalışıyor."
else
    echo "🚀 Ollama başlatılıyor..."
    OLLAMA_RES="/Applications/Ollama.app/Contents/Resources/ollama"
    if [ -f "$OLLAMA_RES" ]; then
        OLLAMA_DEBUG=0 "$OLLAMA_RES" start >> /tmp/ollama.log 2>&1 &
    elif command -v ollama &> /dev/null; then
        ollama start >> /tmp/ollama.log 2>&1 &
    fi
    echo "⏳ Ollama API bekleniyor..."
    READY=0
    for i in $(seq 1 40); do
        if curl -s --max-time 1 http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "✅ Ollama hazır! (${i}x0.5sn)"; READY=1; break
        fi
        sleep 0.5; printf "."
    done
    echo ""
    [ $READY -eq 0 ] && echo "⚠️  Ollama açılmadı — cloud veya mock modda devam."
fi

# ── ELİŞA başlat ──────────────────────────────────────────────────────────
exec python3 -u "$ELISHA_ROOT/app/desktop_app.py"
