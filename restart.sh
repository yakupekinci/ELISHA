#!/bin/bash
# Elişa'yı tamamen durdur ve yeniden başlat
echo "⏹ Elişa durduruluyor..."

# 1) Nazik durdurma (SIGTERM)
pkill -f "desktop_app.py" 2>/dev/null
pkill -f "wake_daemon.py" 2>/dev/null
pkill -f "menubar.py" 2>/dev/null
pkill -f "server.py" 2>/dev/null
sleep 1

# 2) Direnen süreçlere SIGKILL (PortAudio/llama sinyali yutabilir)
pkill -9 -f "desktop_app.py" 2>/dev/null
pkill -9 -f "wake_daemon.py" 2>/dev/null
pkill -9 -f "menubar.py" 2>/dev/null

# 3) Port 8765'i garanti boşalt (eski süreç tutuyorsa yeni başlayamaz)
PORT_PIDS=$(lsof -ti :8765 2>/dev/null)
if [ -n "$PORT_PIDS" ]; then
    echo "$PORT_PIDS" | xargs kill -9 2>/dev/null
    sleep 1
fi

rm -f /tmp/elisha_app.pid /tmp/elisha_wake_daemon.pid /tmp/elisha_menubar.pid
rm -f /tmp/elisha_wake /tmp/elisha_hide
echo "✅ Durdu. Şimdi ELİŞA.command'a çift tıkla."
