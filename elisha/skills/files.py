from pathlib import Path
from .base import BaseSkill

class FilesSkill(BaseSkill):
    name = "files"

    def __init__(self, config: dict):
        self.config = config

    def can_handle(self, action: str) -> bool:
        return action in ["create_file", "read_file", "list_files", "delete_file"]

    def execute(self, action: str, params: dict) -> str:
        try:
            if action == "create_file":
                return self._create(params.get("path", ""), params.get("content", ""))
            elif action == "read_file":
                return self._read(params.get("path", ""))
            elif action == "list_files":
                return self._list(params.get("path", ""))
            elif action == "delete_file":
                return self._delete(params.get("path", ""))
        except Exception as e:
            return f"Dosya hatası: {e}"
        return "Bilinmeyen dosya komutu"

    def _resolve(self, p: str) -> Path:
        if not p:
            p = "~/Desktop"
        path = Path(p).expanduser().resolve()
        return path

    def _create(self, path: str, content: str) -> str:
        if not path:
            return "Dosya yolu boş."
        f = self._resolve(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content or "ELİŞA tarafından oluşturuldu", encoding="utf-8")
        return f"Dosya oluşturuldu: {f}"

    def _read(self, path: str) -> str:
        f = self._resolve(path)
        if not f.exists():
            return f"Dosya bulunamadı: {f}"
        if f.is_dir():
            return f"Klasör: {f} - list_files kullan."
        text = f.read_text(encoding="utf-8", errors="ignore")
        if len(text) > 2000:
            text = text[:2000] + "\n... (kısaltıldı)"
        return f"{f} içeriği:\n{text}"

    def _list(self, path: str) -> str:
        p = self._resolve(path or "~/Desktop")
        if not p.exists():
            return f"Yol bulunamadı: {p}"
        if p.is_file():
            return f"Dosya: {p}"
        items = list(p.iterdir())
        if not items:
            return f"Klasör boş: {p}"
        lines = [f"{'[D]' if x.is_dir() else '[F]'} {x.name}" for x in sorted(items)[:50]]
        return f"{p} içinde {len(items)} öğe:\n" + "\n".join(lines)

    def _delete(self, path: str) -> str:
        f = self._resolve(path)
        if not f.exists():
            return f"Dosya yok: {f}"
        if f.is_dir():
            return "Klasör silme kapalı (güvenlik)."
        f.unlink()
        return f"Silindi: {f}"
