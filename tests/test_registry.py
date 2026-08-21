"""ToolRegistry + temel araç testleri (AŞAMA 21)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from elisha.tools import build_default_registry


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = build_default_registry({})

    def test_18_araç_kayıtlı(self):
        self.assertGreaterEqual(len(self.reg.names()), 18)

    def test_ollama_formati(self):
        tools = self.reg.to_ollama_tools()
        self.assertGreaterEqual(len(tools), 18)
        for t in tools:
            self.assertEqual(t["type"], "function")
            fn = t["function"]
            self.assertIn("name", fn)
            self.assertIn("description", fn)
            self.assertIn("parameters", fn)

    def test_bilinmeyen_arac(self):
        r = self.reg.execute("yok_boyle_arac", {})
        self.assertFalse(r.success)

    def test_get_time(self):
        r = self.reg.execute("get_time", {})
        self.assertTrue(r.success)
        self.assertIn(":", r.message)

    def test_get_date(self):
        r = self.reg.execute("get_date", {})
        self.assertTrue(r.success)


if __name__ == "__main__":
    unittest.main(verbosity=2)
