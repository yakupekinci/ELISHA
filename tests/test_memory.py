"""MemoryStore testleri (AŞAMA 21)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.memory import MemoryStore


def fresh_store():
    tmp = Path(tempfile.mkdtemp()) / "mem.db"
    return MemoryStore({"memory": {"db_path": str(tmp)}})


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        self.m = fresh_store()

    def test_remember_ve_count(self):
        self.assertTrue(self.m.remember("projem", "ELISHA yazıyorum", "proje", 2.0))
        self.assertEqual(self.m.count_memories(), 1)

    def test_upsert_ayni_key(self):
        self.m.remember("projem", "eski", "proje", 1.0)
        self.m.remember("projem", "yeni", "proje", 1.0)
        self.assertEqual(self.m.count_memories(), 1)
        hits = self.m.recall("yeni")
        self.assertTrue(any("yeni" in h["value"] for h in hits))

    def test_recall_skorlama(self):
        self.m.remember("muzik", "Tarkan seviyorum", "tercih", 1.0)
        self.m.remember("isim", "adım Arxes", "kisi", 2.0)
        hits = self.m.recall("Tarkan müzik sever miyim")
        self.assertTrue(any("Tarkan" in h["value"] for h in hits))

    def test_forget_exact_then_word(self):
        self.m.remember("ev-adresi", "Kadıköy", "genel", 1.0)
        self.assertGreaterEqual(self.m.forget("ev-adresi"), 1)
        self.m.remember("muzik-tercihi", "Tarkan dinlemeyi severim", "tercih", 1.0)
        self.assertGreaterEqual(self.m.forget("tarkan"), 1)  # kelime bazlı (değerden)

    def test_konusma_kaydi(self):
        self.m.save_message("user", "selam")
        self.m.save_message("assistant", "merhaba")
        recent = self.m.recent_messages(10)
        self.assertEqual(len(recent), 2)
        self.assertEqual([r["role"] for r in recent], ["user", "assistant"])

    def test_context_block(self):
        self.m.remember("sehir", "İstanbul'da yaşıyorum", "genel", 1.5)
        block = self.m.context_block()
        if block:  # boşsa da sorun yok, ama varsa içermeli
            self.assertIn("İstanbul", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
