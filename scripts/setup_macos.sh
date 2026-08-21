#!/bin/bash
set -e
echo "=== ELİŞA macOS Kurulum ==="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=== Piper Türkçe ses indiriliyor (50MB) ==="
mkdir -p voices
cd voices
if [ ! -f "tr_TR-dfki-medium.onnx" ]; then
  echo "İndiriliyor..."
  curl -L -o tr_TR-dfki-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx
  curl -L -o tr_TR-dfki-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx.json
  echo "✅ Piper sesi hazır"
else
  echo "✅ Zaten var"
fi
cd ..

echo ""
echo "=== Ollama kontrol ==="
if command -v ollama &> /dev/null; then
  echo "Ollama bulundu, model çekiliyor..."
  ollama pull qwen2.5:3b || echo "Model indirilemedi, sonra dene: ollama pull qwen2.5:3b"
else
  echo "Ollama yok. İndir: https://ollama.com/download"
  echo "Sonra: ollama pull qwen2.5:3b"
fi

echo ""
echo "✅ Kurulum bitti! Çalıştır:"
echo "  source venv/bin/activate"
echo "  python -m app.cli --mock   # test (klavye)"
echo "  python app/desktop.py      # UI"
echo "  python -m app.cli          # sesli"
