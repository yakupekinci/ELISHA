"""Güvenlik / PermissionManager testleri (AŞAMA 21)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.security import PermissionManager, NeedConfirmation
from elisha.tools import build_default_registry


class TestPermissions(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager({"security": {"require_confirmation_for": ["HIGH", "CRITICAL"]}})
        # delete_file config kapılı — test için açıkça etkinleştir
        self.reg = build_default_registry({
            "tools": {"delete_file": {"enabled": True}}
        })

    def test_delete_yuksek_risk(self):
        self.assertTrue(self.pm.needs_confirmation(self.reg, "delete_file"))

    def test_get_time_guvenli(self):
        self.assertFalse(self.pm.needs_confirmation(self.reg, "get_time"))

    def test_onay_akisi_evet(self):
        q = self.pm.build_question(self.reg, "delete_file", {"path": "~/Desktop/a.txt"})
        self.assertIn("a.txt", q)
        self.pm.request("delete_file", {"path": "~/Desktop/a.txt"}, q)
        res = self.pm.classify_reply("evet onaylıyorum")
        self.assertTrue(res)
        # resolve: dosya yok -> araç hata verir ama ÇALIŞTI (onay geçti)
        r = self.pm.resolve(self.reg, "evet")
        self.assertIsNotNone(r)

    def test_onay_akisi_hayir(self):
        self.pm.request("delete_file", {"path": "x"}, "soru?")
        r = self.pm.resolve(self.reg, "hayır vazgeç")
        self.assertIsNotNone(r)  # iptal mesajı döner
        self.assertFalse(self.pm.has_pending())

    def test_alakasiz_cevap_reminder(self):
        self.pm.request("delete_file", {"path": "x"}, "soru?")
        r = self.pm.resolve(self.reg, "hava nasıl")
        self.assertIsNone(r)  # None -> orchestrator reminder gösterir
        self.assertTrue(self.pm.has_pending())


if __name__ == "__main__":
    unittest.main(verbosity=2)
