import unittest
from unittest.mock import Mock

import requests

from utilities import overhead


SEATTLE_ZONE = {
    "tl_y": 47.7119,
    "tl_x": -122.4707,
    "br_y": 47.3648,
    "br_x": -122.0900,
}


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class OverheadTests(unittest.TestCase):
    def setUp(self):
        self.original_min_altitude = overhead.MIN_ALTITUDE
        self.original_max_altitude = overhead.MAX_ALTITUDE
        overhead.MIN_ALTITUDE = 1000
        overhead.MAX_ALTITUDE = 20000

    def tearDown(self):
        overhead.MIN_ALTITUDE = self.original_min_altitude
        overhead.MAX_ALTITUDE = self.original_max_altitude

    def test_home_with_bad_longitude_falls_back_to_zone_center(self):
        geometry = overhead._zone_geometry(SEATTLE_ZONE)
        home = overhead._home_position(geometry, [47.6, 122.4, 0])
        self.assertEqual(home, (geometry[4], geometry[5]))

    def test_rate_limit_sets_retry_delay_and_keeps_last_good_data(self):
        session = Mock()
        session.headers = {}
        session.get.return_value = FakeResponse(
            {}, status_code=429, headers={"Retry-After": "120"}
        )
        tracker = overhead.Overhead(session=session)
        tracker._data = [{"callsign": "KEEP"}]
        tracker._grab_data()
        self.assertEqual(tracker.data, [{"callsign": "KEEP"}])
        self.assertFalse(tracker.new_data)
        self.assertGreaterEqual(tracker._next_fetch_at - overhead.monotonic(), 119)
        tracker.grab_data()
        self.assertEqual(session.get.call_count, 1)

    def test_live_data_is_filtered_sorted_and_mapped_for_scenes(self):
        live_payload = {
            "ac": [
                {
                    "hex": "abc123",
                    "flight": " UAL2483 ",
                    "r": "N487UA",
                    "t": "A320",
                    "lat": 47.60,
                    "lon": -122.30,
                    "alt_baro": 5100,
                    "gs": 244.6,
                    "track": 176.7,
                    "baro_rate": -832,
                    "squawk": "6676",
                },
                {
                    "hex": "too-low",
                    "flight": "LOW1",
                    "lat": 47.61,
                    "lon": -122.31,
                    "alt_baro": 500,
                },
                {
                    "hex": "outside",
                    "flight": "FAR1",
                    "lat": 48.5,
                    "lon": -122.30,
                    "alt_baro": 5000,
                },
            ]
        }
        detail_payload = {
            "response": {
                "aircraft": {"type": "Airbus A320-232"},
                "flightroute": {
                    "origin": {"iata_code": "SFO"},
                    "destination": {"iata_code": "SEA"},
                    "airline": {"name": "United Airlines"},
                },
            }
        }
        session = Mock()
        session.headers = {}
        session.get.side_effect = [
            FakeResponse(live_payload),
            FakeResponse(detail_payload),
            FakeResponse(live_payload),
        ]

        tracker = overhead.Overhead(session=session)
        tracker._zone = overhead._zone_geometry(SEATTLE_ZONE)
        tracker._home = (47.59, -122.31)
        tracker._grab_data()

        self.assertTrue(tracker.new_data)
        self.assertEqual(
            tracker.data,
            [
                {
                    "plane": "Airbus A320-232",
                    "origin": "SFO",
                    "destination": "SEA",
                    "vertical_speed": -832,
                    "altitude": 5100,
                    "heading": 177,
                    "callsign": "UAL2483",
                    "ground_speed": 245,
                    "airline": "United Airlines",
                    "squawk": "6676",
                }
            ],
        )
        self.assertEqual(session.get.call_count, 2)

        # Repeated aircraft details come from the six-hour in-memory cache.
        tracker._grab_data()
        self.assertEqual(session.get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
