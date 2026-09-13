import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_interface import app as web


CONFIG = '''ZONE_HOME = {
    "tl_y": 47.7,
    "tl_x": -122.5,
    "br_y": 47.3,
    "br_x": -122.0,
}
LOCATION_HOME = [
    47.5,
    -122.3,
    0.1,
]
WEATHER_LOCATION = "Seattle"
TEMPERATURE_UNITS = "imperial"
TIME_FORMAT_24H = False
BRIGHTNESS = 66
JOURNEY_CODE_SELECTED = "SEA"
MIN_ALTITUDE = 1000
MAX_ALTITUDE = 20000
MIN_GROUNDSPEED = None
MAX_GROUNDSPEED = None
TIMEZONE = "US/Pacific"
'''


class WebInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.config_path = root / "config.py"
        self.settings_path = root / "plane_details.json"
        self.config_path.write_text(CONFIG)
        self.settings_path.write_text('{"fields": ["plane", "route"]}')
        self.config_patch = patch.object(web, "CONFIG_FILE_PATH", str(self.config_path))
        self.settings_patch = patch.object(web, "SETTINGS_FILE", str(self.settings_path))
        self.restart_patch = patch.object(web, "restart_service", return_value=(True, "ok"))
        self.config_patch.start()
        self.settings_patch.start()
        self.restart = self.restart_patch.start()
        web.app.config.update(TESTING=True)
        self.client = web.app.test_client()

    def tearDown(self):
        self.restart_patch.stop()
        self.settings_patch.stop()
        self.config_patch.stop()
        self.tempdir.cleanup()

    def test_page_contains_embedded_map_without_geojson_workflow(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="tracking-map"', html)
        self.assertIn("vendor/leaflet/leaflet.js", html)
        self.assertNotIn("geojson.io", html)
        self.assertNotIn("Paste GeoJSON", html)

    def test_map_form_updates_home_and_normalizes_search_corners(self):
        response = self.client.post(
            "/",
            data={
                "map_settings_form": "1",
                "latitude": "47.61",
                "longitude": "-122.33",
                "altitude": "328.084",
                # Deliberately submit the corners in reverse order.
                "tl_y": "47.2",
                "tl_x": "-122.0",
                "br_y": "47.8",
                "br_x": "-122.6",
            },
        )
        self.assertEqual(response.status_code, 200)
        updated = self.config_path.read_text()
        self.assertIn('"tl_y": 47.8', updated)
        self.assertIn('"tl_x": -122.6', updated)
        self.assertIn('"br_y": 47.2', updated)
        self.assertIn('"br_x": -122.0', updated)
        self.assertIn("    47.61,  # Latitude", updated)
        self.assertIn("    -122.33,  # Longitude", updated)
        self.restart.assert_called_once_with("itsaplane.service")


if __name__ == "__main__":
    unittest.main()
