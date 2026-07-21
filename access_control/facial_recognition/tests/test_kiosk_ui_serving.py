import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from access_control.facial_recognition.src.api import main as api_main


class KioskUiServingTests(unittest.TestCase):
    def test_serves_built_kiosk_ui_and_assets(self):
        old_dist = api_main._KIOSK_UI_DIST
        old_index = api_main._KIOSK_UI_INDEX
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            assets = dist / "assets"
            assets.mkdir()
            (dist / "index.html").write_text("<html>Kiosk UI</html>", encoding="utf-8")
            (assets / "app.js").write_text("console.log('kiosk')", encoding="utf-8")
            api_main._KIOSK_UI_DIST = dist
            api_main._KIOSK_UI_INDEX = dist / "index.html"

            try:
                client = TestClient(api_main.app)
                page = client.get("/ui/")
                asset = client.get("/ui/assets/app.js")
                legacy_asset = client.get("/assets/app.js")
            finally:
                api_main._KIOSK_UI_DIST = old_dist
                api_main._KIOSK_UI_INDEX = old_index

        self.assertEqual(page.status_code, 200)
        self.assertIn("Kiosk UI", page.text)
        self.assertEqual(asset.status_code, 200)
        self.assertIn("console.log", asset.text)
        self.assertEqual(legacy_asset.status_code, 200)
        self.assertIn("console.log", legacy_asset.text)


if __name__ == "__main__":
    unittest.main()
