"""AŞAMA 6 — RunShellTool testleri."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.tools import build_default_registry
from elisha.tools.shell_tool import RunShellTool
from elisha.security import PermissionManager


class TestShellTool(unittest.TestCase):
    def setUp(self):
        self.cfg = {"tools": {"run_shell": {"enabled": True,
                                            "allowlist": ["uptime", "ls"],
                                            "timeout": 5}}}
        self.reg = build_default_registry(self.cfg)

    def test_varsayilan_kapali(self):
        reg = build_default_registry({})
        self.assertNotIn("run_shell", reg.names())

    def test_acikca_kayitli(self):
        self.assertIn("run_shell", self.reg.names())

    def test_allowlist_disi_reddi(self):
        r = self.reg.execute("run_shell", {"command": "rm -rf /"})
        self.assertFalse(r.success)

    def test_allowlist_ici_calisir(self):
        r = self.reg.execute("run_shell", {"command": "uptime"})
        self.assertTrue(r.success)
        self.assertTrue(len(r.message) > 0)

    def test_boru_hatti_gecmez(self):
        # shlex ile ayrışınca '|' allowlist ilk kelimesini bozmaz ama
        # ikinci komut da allowlist'te olmalı -> ls izinli, echo değil
        r = self.reg.execute("run_shell", {"command": "ls | echo merhaba"})
        self.assertFalse(r.success)  # shlex tek komut olarak görür, 'ls' ilk kelime...
        # NOT: pipe karakteri shlex.split'a göre 'ls' '|' 'echo'... ilk kelime ls ->
        # aslında subprocess argüman olarak '|' alır, güvenli (shell yok).

    def test_critical_risk_onay_ister(self):
        pm = PermissionManager({"security": {"require_confirmation_for": ["CRITICAL"]}})
        self.assertTrue(pm.needs_confirmation(self.reg, "run_shell"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
