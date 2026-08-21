Write-Host "=== ELİŞA Windows Kurulum ===" -ForegroundColor Cyan
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

Write-Host ""
Write-Host "=== Piper Türkçe ses ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path voices | Out-Null
Set-Location voices
if (-not (Test-Path "tr_TR-dfki-medium.onnx")) {
  Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx" -OutFile "tr_TR-dfki-medium.onnx"
  Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx.json" -OutFile "tr_TR-dfki-medium.onnx.json"
  Write-Host "✅ Piper sesi hazır" -ForegroundColor Green
} else {
  Write-Host "✅ Zaten var" -ForegroundColor Green
}
Set-Location ..

Write-Host ""
Write-Host "Ollama yoksa indir: https://ollama.com/download" -ForegroundColor Yellow
Write-Host "Sonra: ollama pull qwen2.5:3b" -ForegroundColor Yellow
Write-Host ""
Write-Host "✅ Bitti! Çalıştır:" -ForegroundColor Green
Write-Host "  .\venv\Scripts\Activate.ps1"
Write-Host "  python -m app.cli --mock"
Write-Host "  python app/desktop.py"
