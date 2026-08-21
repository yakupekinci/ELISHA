#!/bin/bash
# ELİŞA başlatıcı — tek giriş noktası
cd "$(dirname "$0")"
export PATH="/Users/arxes/.local/bin:$PATH"
open -a Ollama 2>/dev/null; sleep 2
exec python3 -u app/desktop_app.py
