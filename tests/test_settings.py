"""Settings persistence tests."""
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSettings(unittest.TestCase):
    def setUp(self):
        """Use a temp directory so we don't pollute real ~/.config."""
        self.tmp_dir = tempfile.mkdtemp()
        self.settings_file = Path(self.tmp_dir) / "settings.yaml"
        # Patch module-level paths
        import elisha.settings as mod
        self._orig_dir = mod._SETTINGS_DIR
        self._orig_file = mod._SETTINGS_FILE
        mod._SETTINGS_DIR = Path(self.tmp_dir)
        mod._SETTINGS_FILE = self.settings_file
        mod._cache = None  # Reset cache

    def tearDown(self):
        import elisha.settings as mod
        mod._SETTINGS_DIR = self._orig_dir
        mod._SETTINGS_FILE = self._orig_file
        mod._cache = None
        # Cleanup
        if self.settings_file.exists():
            self.settings_file.unlink()
        os.rmdir(self.tmp_dir)

    def test_defaults_returned_when_no_file(self):
        from elisha import settings
        self.assertEqual(settings.get("tts_enabled"), True)
        self.assertEqual(settings.get("theme"), "dark")
        self.assertEqual(settings.get("provider"), "auto")

    def test_set_persists_to_disk(self):
        from elisha import settings
        settings.set("tts_enabled", False)
        # File should exist now
        self.assertTrue(self.settings_file.exists())
        # Read raw YAML to confirm
        import yaml
        with open(self.settings_file) as f:
            data = yaml.safe_load(f)
        self.assertFalse(data["tts_enabled"])

    def test_persistence_across_reload(self):
        from elisha import settings
        settings.set("theme", "light")
        settings.set("volume", 0.5)
        # Simulate restart by clearing cache and reloading
        settings._cache = None
        self.assertEqual(settings.get("theme"), "light")
        self.assertEqual(settings.get("volume"), 0.5)
        # Defaults still present for unset keys
        self.assertEqual(settings.get("speed"), 1.0)

    def test_set_many(self):
        from elisha import settings
        settings.set_many({"wake_enabled": True, "voice": "custom-voice"})
        self.assertEqual(settings.get("wake_enabled"), True)
        self.assertEqual(settings.get("voice"), "custom-voice")

    def test_get_all_returns_merged(self):
        from elisha import settings
        all_s = settings.get_all()
        # Should have all default keys
        self.assertIn("tts_enabled", all_s)
        self.assertIn("wake_enabled", all_s)
        self.assertIn("provider", all_s)
        self.assertIn("voice", all_s)
        self.assertIn("speed", all_s)
        self.assertIn("volume", all_s)
        self.assertIn("theme", all_s)

    def test_reset(self):
        from elisha import settings
        settings.set("theme", "solar")
        settings.reset()
        self.assertEqual(settings.get("theme"), "dark")

    def test_unknown_key_returns_none(self):
        from elisha import settings
        self.assertIsNone(settings.get("nonexistent_key"))

    def test_unknown_key_with_default(self):
        from elisha import settings
        self.assertEqual(settings.get("nonexistent_key", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
