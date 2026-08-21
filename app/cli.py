"""
ELİŞA CLI - Terminalden çalıştır
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.orchestrator import ElishaOrchestrator

def main():
    parser = argparse.ArgumentParser(description="ELİŞA - Sesli Asistan CLI")
    parser.add_argument("--mock", action="store_true", help="Sadece klavye (mikrofon/TTS olmadan test)")
    parser.add_argument("--text", type=str, help="Tek seferlik metin işle")
    parser.add_argument("--config", type=str, help="config.yaml yolu")
    args = parser.parse_args()

    bot = ElishaOrchestrator(config_path=args.config)

    if args.text:
        resp = bot.run_cli_once(args.text, speak=not args.mock)
        print(resp)
        return

    if args.mock:
        print("🧪 Mock mod: klavyeden yaz, ELİŞA cevaplasın (STT/TTS atlanıyor)")
        print("Çıkmak için: çık / exit")
        while True:
            try:
                t = input("\n👤 Sen: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not t:
                continue
            if t.lower() in ["çık", "exit", "quit", "kapat"]:
                print("👋 Görüşürüz!")
                break
            resp = bot.process_text(t)
            print(f"🤖 ELİŞA: {resp}")
        return

    # normal sesli döngü
    bot.run_voice_loop()

if __name__ == "__main__":
    main()
