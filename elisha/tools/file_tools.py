import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

from .base import Tool, ToolResult, RiskLevel

_HOME = Path.home()
_KNOWN_DIRS = {
    "desktop": "Desktop", "masaüstü": "Desktop", "masaustu": "Desktop",
    "downloads": "Downloads", "indirilenler": "Downloads",
    "documents": "Documents", "belgeler": "Documents",
}


def _resolve(p) -> Path:
    """Model'in uydurduğu yolları gerçek kullanıcı dizinine çevir."""
    p = str(p or "").strip().strip('"').strip("'")
    if not p:
        return _HOME / "Desktop"
    low = p.lower().rstrip("/")
    if low in _KNOWN_DIRS:
        return _HOME / _KNOWN_DIRS[low]
    m = re.match(r"^/(Desktop|Downloads|Documents|Pictures|Music|Movies|Public)(/.*)?$", p, re.I)
    if m:
        p = "~/" + p.lstrip("/")
    m = re.match(r"^/Users/[^/]+(/.*)?$", p)
    if m and not p.startswith(str(_HOME)):
        p = "~" + (m.group(1) or "")
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = _HOME / path
    return path.resolve()


PATH_HINT = ("Yol formatı: '~/Desktop', '~/Downloads' gibi ~ kullan. "
             "Masaüstü=~/Desktop, İndirilenler=~/Downloads, Belgeler=~/Documents.")


class ListFilesTool(Tool):
    name = "list_files"
    description = ("Bir klasördeki dosya ve klasörleri listeler. Kullanıcı 'dosyaları listele', 'klasörü göster' "
                   "derse kullan. path parametresi klasör yolu; boşsa Masaüstü listelenir. "
                   "Örnekler: ~/Desktop, ~/Downloads, ~/Documents.")
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Klasör yolu, örn. ~/Downloads"}},
        "required": [],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        p = _resolve(args.get("path", ""))
        if not p.exists():
            return ToolResult(False, self.name, error=f"Yol bulunamadı: {p}")
        if p.is_file():
            return ToolResult(True, self.name, message=f"Dosya: {p}", data={"path": str(p)})
        items: List[Dict[str, Any]] = []
        for x in sorted(p.iterdir())[:100]:
            items.append({"name": x.name, "type": "dir" if x.is_dir() else "file",
                          "size": x.stat().st_size if x.is_file() else 0})
        if not items:
            return ToolResult(True, self.name, message=f"Klasör boş: {p}",
                              data={"path": str(p), "items": []})
        lines = [f"[{'D' if i['type'] == 'dir' else 'F'}] {i['name']}" for i in items[:50]]
        return ToolResult(True, self.name,
                          message=f"{p} içinde {len(items)} öğe:\n" + "\n".join(lines),
                          data={"path": str(p), "count": len(items), "items": items})


class ReadFileTool(Tool):
    name = "read_file"
    description = ("Bir dosyanın içeriğini okur (metin VE PDF). Kullanıcı dosya okumayı, "
                   "PDF özetlemeyi veya belge hakkında soru sormayı isterse kullan. "
                   "path parametresi zorunlu. Görsellerde kullanma — analyze_screen ya da "
                   "açıklama ister.")
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Okunacak dosyanın tam yolu"}},
        "required": ["path"],
    }
    risk_level = RiskLevel.SAFE

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        f = _resolve(args.get("path", ""))
        if not f.exists():
            return ToolResult(False, self.name, error=f"Dosya bulunamadı: {f}")
        if f.is_dir():
            return ToolResult(False, self.name, error=f"{f} bir klasör, read_file yerine list_files kullan.")
        # PDF: pypdf ile metin çıkart (Mark-LI 'File Processor' esinli)
        if f.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(f))
                pages = []
                for i, page in enumerate(reader.pages[:10]):
                    pages.append(page.extract_text() or "")
                text = "\n".join(pages).strip()
                n = len(reader.pages)
                if not text:
                    return ToolResult(False, self.name,
                                      error=f"'{f.name}' PDF'inden metin çıkartılamadı (taranmış/görsel olabilir).")
                note = f" (ilk {min(10, n)}/{n} sayfa)" if n > 10 else ""
                return ToolResult(True, self.name,
                                  message=f"'{f.name}' okundu{note}. İçerik:",
                                  data={"text": text[:6000], "pages": n})
            except Exception as e:
                return ToolResult(False, self.name, error=f"PDF okunamadı: {e}")
        # Görsel / ikili dosya koruması: metin modeli görsel analiz edemez,
        # ham okuma bozuk karakter üretir ve sağlayıcı hatasına yol açar.
        _IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".heic", ".ico", ".svg", ".zip", ".dmg", ".app"}
        _IMG_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM", b"%PDF", b"PK\x03\x04")
        try:
            head = f.open("rb").read(16)
        except Exception:
            head = b""
        if f.suffix.lower() in _IMG_EXT or any(head.startswith(m) for m in _IMG_MAGIC):
            return ToolResult(
                False, self.name,
                error=(f"'{f.name}' bir ikili/görsel dosya; metin olarak okunamaz ve "
                       "görsel analizi yapılamıyor. Kullanıcıya bunu açıkla; ekran görüntüsü "
                       "analizi şu an desteklenmiyor."),
            )
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return ToolResult(False, self.name, error=f"Okunamadı: {e}")
        truncated = len(text) > 2000
        shown = text[:2000] + ("\n... (kısaltıldı)" if truncated else "")
        return ToolResult(True, self.name, message=shown,
                          data={"path": str(f), "size": len(text), "truncated": truncated})


class CreateFileTool(Tool):
    name = "create_file"
    description = ("Yeni bir dosya oluşturur ve içine içerik yazar. Kullanıcı 'dosya oluştur', 'not al' derse "
                   "kullan. path ve content parametreleri gerekir. Var olan dosyanın üzerine yazar."
                   + " " + PATH_HINT)
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Oluşturulacak dosya yolu, örn. ~/Desktop/not.txt"},
            "content": {"type": "string", "description": "Dosyaya yazılacak metin"},
        },
        "required": ["path"],
    }
    risk_level = RiskLevel.MEDIUM

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        content = args.get("content") or "ELİŞA tarafından oluşturuldu"
        if not path:
            return ToolResult(False, self.name, error="Dosya yolu boş.")
        f = _resolve(path)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(content), encoding="utf-8")
            return ToolResult(True, self.name, message=f"Dosya oluşturuldu: {f}", data={"path": str(f)})
        except Exception as e:
            return ToolResult(False, self.name, error=str(e))


class WriteFileTool(Tool):
    name = "write_file"
    description = ("Var olan bir dosyaya içerik ekler/yazar (sonuna ekler). Dosyayı sıfırdan oluşturmak için "
                   "create_file kullan. path ve content parametreleri gerekir."
                   + " " + PATH_HINT)
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Yazılacak dosya yolu"},
            "content": {"type": "string", "description": "Eklenecek metin"},
        },
        "required": ["path", "content"],
    }
    risk_level = RiskLevel.MEDIUM

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        f = _resolve(args.get("path", ""))
        content = str(args.get("content", ""))
        if not f.exists():
            return ToolResult(False, self.name, error=f"Dosya bulunamadı: {f}, önce create_file kullan.")
        try:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(content + "\n")
            return ToolResult(True, self.name, message=f"İçerik eklendi: {f}", data={"path": str(f)})
        except Exception as e:
            return ToolResult(False, self.name, error=str(e))


class CopyFileTool(Tool):
    name = "copy_file"
    description = ("Bir dosyayı başka bir konuma kopyalar (orijinal kalır). source ve destination "
                   "parametreleri gerekir. Klasör kopyalamayı desteklemez."
                   + " " + PATH_HINT)
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Kaynak dosya yolu"},
            "destination": {"type": "string", "description": "Hedef yol (klasör veya dosya adı)"},
        },
        "required": ["source", "destination"],
    }
    risk_level = RiskLevel.MEDIUM

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        src = _resolve(args.get("source", ""))
        dst = _resolve(args.get("destination", ""))
        if not src.exists():
            return ToolResult(False, self.name, error=f"Kaynak bulunamadı: {src}")
        if src.is_dir():
            return ToolResult(False, self.name, error="Klasör kopyalama desteklenmiyor.")
        try:
            if dst.is_dir():
                dst = dst / src.name
            shutil.copy2(src, dst)
            return ToolResult(True, self.name,
                              message=f"Kopyalandı: {src.name} -> {dst}",
                              data={"source": str(src), "destination": str(dst)})
        except Exception as e:
            return ToolResult(False, self.name, error=str(e))


class MoveFileTool(Tool):
    name = "move_file"
    description = ("Bir dosyayı başka bir konuma taşır (orijinal yerinden silinir). source ve destination "
                   "parametreleri gerekir. Kalıcı taşıma işlemidir."
                   + " " + PATH_HINT)
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Taşınacak dosya yolu"},
            "destination": {"type": "string", "description": "Hedef yol (klasör veya dosya adı)"},
        },
        "required": ["source", "destination"],
    }
    risk_level = RiskLevel.MEDIUM

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        src = _resolve(args.get("source", ""))
        dst = _resolve(args.get("destination", ""))
        if not src.exists():
            return ToolResult(False, self.name, error=f"Kaynak bulunamadı: {src}")
        try:
            if dst.is_dir():
                dst = dst / src.name
            shutil.move(str(src), str(dst))
            return ToolResult(True, self.name,
                              message=f"Taşındı: {src.name} -> {dst}",
                              data={"source": str(src), "destination": str(dst)})
        except Exception as e:
            return ToolResult(False, self.name, error=str(e))


class DeleteFileTool(Tool):
    name = "delete_file"
    description = ("Tek bir dosyayı kalıcı olarak siler. Kullanıcı açıkça silme isterse kullan; "
                   "işlem geri alınamaz ve onay gerektirir. Klasör silme desteklenmez. "
                   "path parametresi zorunlu.")
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Silinecek dosyanın yolu"}},
        "required": ["path"],
    }
    risk_level = RiskLevel.HIGH

    def confirm_message(self, args: Dict[str, Any]) -> str:
        return f"'{args.get('path', '?')}' dosyası kalıcı olarak silinecek. Onaylıyor musun?"

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        f = _resolve(args.get("path", ""))
        if not f.exists():
            f = self._find_by_name(f.name)
        if f is None:
            return ToolResult(False, self.name, error=f"Dosya yok: {args.get('path', '?')}")
        if f.is_dir():
            return ToolResult(False, self.name, error="Klasör silme kapalı (güvenlik).")
        try:
            f.unlink()
            return ToolResult(True, self.name, message=f"Silindi: {f}", data={"path": str(f)})
        except Exception as e:
            return ToolResult(False, self.name, error=str(e))

    @staticmethod
    def _find_by_name(name: str):
        """Model/STT yol uydurduysa bilinen klasörlerde dosya adıyla ara."""
        if not name:
            return None
        for base in ("Desktop", "Downloads", "Documents"):
            cand = _HOME / base / name
            if cand.is_file():
                return cand
        return None
