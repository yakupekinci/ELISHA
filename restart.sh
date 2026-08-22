#!/bin/bash
# Elişa'yı tamamen durdur ve yeniden başlat
echo "⏹ Elişa durduruluyor..."
pkill -f "desktop_app.py" 2>/dev/null
pkill -f "wake_daemon.py" 2>/dev/null  
pkill -f "menubar.py" 2>/dev/null
pkill -f "server.py" 2>/dev/null
sleep 1
rm -f /tmp/elisha_app.pid /tmp/elisha_wake_daemon.pid /tmp/elisha_menubar.pid
rm -f /tmp/elisha_wake /tmp/elisha_hide
echo "✅ Durdu. Şimdi ELİŞA.command'a çift tıkla."
