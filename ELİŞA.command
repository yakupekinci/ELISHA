#!/bin/bash
cd "$(dirname "$0")"
export PATH="/Users/arxes/.local/bin:$PATH"
open -a Ollama 2>/dev/null; sleep 2
python3 -u app/desktop.py
