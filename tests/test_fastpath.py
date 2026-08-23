"""FastPath yönlendirme testleri (AŞAMA 21)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.fastpath import FastPath
from elisha.security import NeedConfirmation, PermissionManager
from elisha.tools import build_default_registry


def make_fp(memory=False, permissions=False):
    # delete_file/run_shell config kapılı — testlerde açıkça aç
    cfg = {"tools": {"delete_file": {"enabled": True}, "run_shell": {"enabled": True}}}
    reg = build_default_registry(cfg)
    mem = None
    if memory:
        from elisha.memory import MemoryStore
        tmp = Path(tempfile.mkdtemp()) / "test.db"
        mem = MemoryStore({"memory": {"db_path": str(tmp)}})
    pm = PermissionManager({}) if permissions else None
    return FastPath({}, reg, mem, permissions=pm), mem


class TestFastPathRouting(unittest.TestCase):
    def setUp(self):
        self.fp, _ = make_fp()

    def test_bos_metin(self):
        self.assertIsNone(self.fp.try_route(""))

    def test_saat(self):
        r = self.fp.try_route("saat kaç")
        self.assertIsNotNone(r)
        self.assertIn(":", r)

    def test_tarih(self):
        r = self.fp.try_route("bugün ayın kaçı")
        self.assertIsNotNone(r)
        self.assertIn("2026", r)

    def test_web_arama(self):
        r = self.fp.try_route("yapay zeka nedir ara")
        self.assertIsNotNone(r)
        # DDGS sonuçları ya hata mesajı; en azından agent'a düşmemeli
        self.assertIsInstance(r, str)

    def test_youtube_onceligi(self):
        # "youtube'da X ara" arama değil site kuralına gitmeli... (şarkı değilse de URL kuralı önce)
        r = self.fp.try_route("youtube aç")
        self.assertEqual(r, "YouTube açılıyor.")

    def test_dosya_olusturma(self):
        import os, time
        p = Path.home() / "Desktop" / f"fptest-{int(time.time())}.txt"
        try:
            r = self.fp.try_route(f"{p.name} dosyası oluştur içeriği merhaba dünya olsun")
            self.assertIsNotNone(r)
            self.assertTrue(p.exists())
            self.assertIn("merhaba", p.read_text(encoding="utf-8"))
        finally:
            p.unlink(missing_ok=True)

    def test_silme_onay_ister(self):
        fp, _ = make_fp(permissions=True)
        with self.assertRaises(NeedConfirmation):
            fp._run("delete_file", {"path": "x.txt"})

    def test_hafiza_hatirla(self):
        fp, mem = make_fp(memory=True)
        r = fp.try_route("bunu hatırla: projem ELISHA")
        self.assertIn("akılda", r.lower())
        hits = mem.recall("ELISHA proje")
        self.assertGreaterEqual(len(hits), 1)


class TestDeleteRouting(unittest.TestCase):
    def test_silme_kurali_yakalar(self):
        fp, _ = make_fp()
        # dosya yok -> araç hata döner ama route YAKALAMALI (None dönmemeli)
        r = fp.try_route("masaustundeki olmayan-dosya-xyz.txt dosyasini sil")
        self.assertIsNotNone(r)

    def test_genel_silme_agent_kalir(self):
        fp, _ = make_fp()
        r = fp.try_route("bu dosyayı sil")
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
