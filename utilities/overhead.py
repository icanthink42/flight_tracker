"""Fetch nearby aircraft from free, keyless ADS-B services."""

import logging
import math
from threading import Lock, Thread
from time import monotonic, sleep
from urllib.parse import quote

import requests


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)

try:
    from config import LOCATION_HOME, MAX_ALTITUDE, MIN_ALTITUDE, ZONE_HOME
except (ModuleNotFoundError, NameError, ImportError):
    ZONE_HOME = {
        "tl_y": 42.029,
        "tl_x": -87.888,
        "br_y": 41.99,
        "br_x": -87.8,
    }
    LOCATION_HOME = [42.0016, -87.8283, 0]
    MIN_ALTITUDE = 950
    MAX_ALTITUDE = 10000

try:
    from config import MAX_GROUNDSPEED, MIN_GROUNDSPEED
except (ModuleNotFoundError, NameError, ImportError):
    MIN_GROUNDSPEED = None
    MAX_GROUNDSPEED = None


LIVE_API_URL = "https://api.adsb.lol/v2/point/{lat}/{lon}/{radius}"
DETAIL_API_URL = "https://api.adsbdb.com/v0/aircraft/{icao}"
REQUEST_TIMEOUT = 10
MAX_FLIGHT_LOOKUP = 5
DETAIL_CACHE_SECONDS = 6 * 60 * 60
EARTH_RADIUS_KM = 6371.0
KM_PER_NAUTICAL_MILE = 1.852
USER_AGENT = "neelemanet-plane-spotter/1.0"


def _number(value):
    """Return a float for numeric API values and None for missing values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.upper() in {"", "N/A", "NONE", "NULL"} else value


def _haversine_km(lat_a, lon_a, lat_b, lon_b):
    lat_a, lon_a, lat_b, lon_b = map(
        math.radians, (lat_a, lon_a, lat_b, lon_b)
    )
    delta_lat = lat_b - lat_a
    delta_lon = lon_b - lon_a
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(value))


def _zone_geometry(zone):
    min_lat, max_lat = sorted((float(zone["tl_y"]), float(zone["br_y"])))
    min_lon, max_lon = sorted((float(zone["tl_x"]), float(zone["br_x"])))
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2
    radius_km = max(
        _haversine_km(center_lat, center_lon, lat, lon)
        for lat in (min_lat, max_lat)
        for lon in (min_lon, max_lon)
    )
    radius_nm = max(1, min(250, math.ceil(radius_km / KM_PER_NAUTICAL_MILE)))
    return min_lat, max_lat, min_lon, max_lon, center_lat, center_lon, radius_nm


def _home_position(zone_geometry, configured_home):
    min_lat, max_lat, min_lon, max_lon, center_lat, center_lon, _ = zone_geometry
    try:
        home_lat, home_lon = map(float, configured_home[:2])
    except (TypeError, ValueError):
        return center_lat, center_lon

    # A home point outside its own search box is almost certainly a sign error.
    if min_lat <= home_lat <= max_lat and min_lon <= home_lon <= max_lon:
        return home_lat, home_lon
    logging.warning("LOCATION_HOME is outside ZONE_HOME; using the zone center")
    return center_lat, center_lon


def _in_zone(aircraft, geometry):
    min_lat, max_lat, min_lon, max_lon, *_ = geometry
    lat = _number(aircraft.get("lat"))
    lon = _number(aircraft.get("lon"))
    return (
        lat is not None
        and lon is not None
        and min_lat <= lat <= max_lat
        and min_lon <= lon <= max_lon
    )


def _passes_filters(aircraft):
    altitude = _number(aircraft.get("alt_baro"))
    if altitude is None:
        altitude = _number(aircraft.get("alt_geom"))
    if altitude is None or not MIN_ALTITUDE < altitude < MAX_ALTITUDE:
        return False

    speed = _number(aircraft.get("gs"))
    if speed is not None:
        if MIN_GROUNDSPEED is not None and speed < MIN_GROUNDSPEED:
            return False
        if MAX_GROUNDSPEED is not None and speed > MAX_GROUNDSPEED:
            return False
    return True


def _airport_code(airport):
    if not isinstance(airport, dict):
        return ""
    # The display's journey layout is designed for three-letter IATA codes.
    return _clean(airport.get("iata_code"))


class Overhead:
    def __init__(self, session=None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._lock = Lock()
        self._data = []
        self._new_data = False
        self._processing = False
        self._detail_cache = {}
        self._zone = _zone_geometry(ZONE_HOME)
        self._home = _home_position(self._zone, LOCATION_HOME)

    def grab_data(self):
        with self._lock:
            if self._processing:
                return
            self._new_data = False
            self._processing = True
        Thread(target=self._grab_data, daemon=True).start()

    def _fetch_live_aircraft(self):
        *_, center_lat, center_lon, radius_nm = self._zone
        url = LIVE_API_URL.format(
            lat=center_lat,
            lon=center_lon,
            radius=radius_nm,
        )
        response = self._session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        aircraft = payload.get("ac", [])
        if not isinstance(aircraft, list):
            raise ValueError("ADSB.lol response did not contain an aircraft list")
        return aircraft

    def _fetch_details(self, aircraft):
        icao = _clean(aircraft.get("hex")).lower().lstrip("~")
        callsign = _clean(aircraft.get("flight")).upper()
        if not icao:
            return {}

        cache_key = (icao, callsign)
        cached = self._detail_cache.get(cache_key)
        if cached and monotonic() - cached[0] < DETAIL_CACHE_SECONDS:
            return cached[1]

        url = DETAIL_API_URL.format(icao=quote(icao, safe=""))
        params = {"callsign": callsign} if callsign else None
        details = {}
        try:
            response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                self._detail_cache[cache_key] = (monotonic(), details)
                return details
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload.get("response"), dict):
                details = payload["response"]
        except (requests.RequestException, ValueError) as error:
            logging.warning("ADSBDB lookup failed for %s: %s", icao, error)

        self._detail_cache[cache_key] = (monotonic(), details)
        return details

    def _distance_to_home(self, aircraft):
        lat = _number(aircraft.get("lat"))
        lon = _number(aircraft.get("lon"))
        return _haversine_km(self._home[0], self._home[1], lat, lon)

    def _display_record(self, live, details):
        aircraft = details.get("aircraft", {})
        route = details.get("flightroute", {})
        airline = route.get("airline") or {}

        altitude = _number(live.get("alt_baro"))
        if altitude is None:
            altitude = _number(live.get("alt_geom"))

        callsign = _clean(live.get("flight"))
        registration = _clean(live.get("r")) or _clean(aircraft.get("registration"))
        if not callsign:
            callsign = registration or _clean(live.get("hex")).upper()

        plane = _clean(aircraft.get("type")) or _clean(live.get("t"))
        vertical_speed = _number(live.get("baro_rate"))
        if vertical_speed is None:
            vertical_speed = _number(live.get("geom_rate"))

        return {
            "plane": plane,
            "origin": _airport_code(route.get("origin")),
            "destination": _airport_code(route.get("destination")),
            "vertical_speed": (
                round(vertical_speed) if vertical_speed is not None else None
            ),
            "altitude": round(altitude) if altitude is not None else None,
            "heading": (
                round(_number(live.get("track")))
                if _number(live.get("track")) is not None
                else None
            ),
            "callsign": callsign,
            "ground_speed": (
                round(_number(live.get("gs")))
                if _number(live.get("gs")) is not None
                else None
            ),
            "airline": _clean(airline.get("name")),
            "squawk": _clean(live.get("squawk")),
        }

    def _grab_data(self):
        succeeded = False
        data = []
        try:
            candidates = [
                aircraft
                for aircraft in self._fetch_live_aircraft()
                if _in_zone(aircraft, self._zone) and _passes_filters(aircraft)
            ]
            candidates.sort(key=self._distance_to_home)
            for live in candidates[:MAX_FLIGHT_LOOKUP]:
                details = self._fetch_details(live)
                data.append(self._display_record(live, details))
            succeeded = True
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            logging.exception("Aircraft refresh failed: %s", error)
        finally:
            with self._lock:
                self._processing = False
                if succeeded:
                    self._data = data
                    self._new_data = True

    @property
    def new_data(self):
        with self._lock:
            return self._new_data

    @property
    def processing(self):
        with self._lock:
            return self._processing

    @property
    def data(self):
        with self._lock:
            self._new_data = False
            return list(self._data)

    @property
    def data_is_empty(self):
        with self._lock:
            return len(self._data) == 0


if __name__ == "__main__":
    overhead = Overhead()
    overhead.grab_data()
    while overhead.processing:
        sleep(0.1)
    print(overhead.data)
