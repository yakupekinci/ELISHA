#!/bin/bash
# ELİŞA anahtar yönetimi — şifreli yedek (AES-256-CBC, PBKDF2)
# Kullanım:
#   ./scripts/secrets.sh restore        → şifreli yedeği geri yükler
#   ./scripts/secrets.sh encrypt        → mevcut secrets.env'i yeniden şifreler
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENC="$ROOT/config/secrets.env.enc"
TARGET="$HOME/.config/elisha/secrets.env"

case "${1:-}" in
  restore)
    [ -f "$ENC" ] || { echo "❌ $ENC yok"; exit 1; }
    read -s -p "🔐 Şifreli anahtar dosyasının parolası: " PASS; echo
    mkdir -p "$(dirname "$TARGET")"
    openssl enc -d -aes-256-cbc -pbkdf2 -in "$ENC" -out "$TARGET" -pass pass:"$PASS" \
      && chmod 600 "$TARGET" \
      && echo "✅ Anahtarlar geri yüklendi → $TARGET (uygulamayı yeniden başlat)" \
      || { echo "❌ Parola hatalı"; rm -f "$TARGET"; exit 1; }
    ;;
  encrypt)
    [ -f "$TARGET" ] || { echo "❌ $TARGET yok"; exit 1; }
    read -s -p "🔑 Yeni parola belirle: " PASS; echo
    openssl enc -aes-256-cbc -pbkdf2 -salt -in "$TARGET" -out "$ENC" -pass pass:"$PASS" \
      && echo "✅ Yeniden şifrelendi → $ENC"
    ;;
  *)
    echo "Kullanım: $0 restore|encrypt"; exit 1 ;;
esac
