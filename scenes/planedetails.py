import json
import os
from rgbmatrix import graphics

from utilities.animator import Animator
from setup import colours, fonts, screen

# ---- Optional master toggle from config.py (kept for convenience) ----
try:
    from config import SHOW_PLANE_DETAILS
except Exception:
    SHOW_PLANE_DETAILS = True

# ---- Settings file (edited by your Flask UI) ----
SETTINGS_FILE = "/home/pi/its-a-plane-python/settings/plane_details.json"

# Default set of fields if settings file is missing
# You can change this default, it’s only used the first time.
DEFAULT_FIELDS = ["plane", "route", "ground_speed", "heading"]

# All supported fields (must match keys in overhead.py data)
ALLOWED_FIELDS = {
    "plane",          # aircraft model/name (string)
    "route",          # "ORIGIN→DEST" using IATA codes (string)
    "callsign",       # callsign (string)
    "airline",        # airline name (string)
    "ground_speed",   # kts (number)
    "heading",        # degrees 0–359 (number)
    "altitude",       # feet (number)
    "vertical_speed", # fpm (number)
    "squawk",         # squawk code (string/number)
}

# Order to render on the display. We’ll include only the ones the user selected.
FIELD_ORDER = [
    "airline",
    "plane",
    "callsign",
    "route",
    "altitude",
    "ground_speed",
    "heading",
    "vertical_speed",
    "squawk",
]

# ---- Visual setup ----
PLANE_DETAILS_COLOUR = colours.PINK
PLANE_DISTANCE_FROM_TOP = 30
PLANE_TEXT_HEIGHT = 9
PLANE_FONT = fonts.regular


def ensure_settings_file():
    """Create default settings file on first run."""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        if not os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "w") as f:
                json.dump({"fields": DEFAULT_FIELDS}, f)
    except Exception:
        # If this fails, we’ll just fall back to defaults at runtime.
        pass


def load_selected_fields():
    """Return list of enabled fields, filtered to allowed ones."""
    ensure_settings_file()
    try:
        with open(SETTINGS_FILE, "r") as f:
            obj = json.load(f)
        fields = obj.get("fields", DEFAULT_FIELDS)
        # sanitize
        fields = [x for x in fields if x in ALLOWED_FIELDS]
        # if user somehow unchecked everything, fall back to defaults
        return fields or DEFAULT_FIELDS
    except Exception:
        return DEFAULT_FIELDS


def fmt_route(d):
    """Format origin→destination, handling blanks."""
    o = (d.get("origin") or "").strip()
    t = (d.get("destination") or "").strip()
    if o and t:
        return f"{o}→{t}"
    return o or t or ""


def fmt_num(val):
    """Turn None into '', keep ints/floats readable."""
    return "" if val is None else str(val)


def build_parts_for_fields(d, selected_fields):
    """Build a list of text parts in the FIELD_ORDER, only for selected fields."""
    parts = []

    for key in FIELD_ORDER:
        if key not in selected_fields:
            continue

        if key == "route":
            r = fmt_route(d)
            if r:
                parts.append(r)

        elif key == "plane":
            v = (d.get("plane") or "").strip()
            if v:
                parts.append(v)

        elif key == "callsign":
            v = (d.get("callsign") or "").strip()
            if v:
                parts.append(v)

        elif key == "airline":
            v = (d.get("airline") or "").strip()
            if v:
                parts.append(v)

        elif key == "ground_speed":
            v = d.get("ground_speed")
            if v is not None:
                parts.append(f"{fmt_num(v)} kts")

        elif key == "heading":
            v = d.get("heading")
            if v is not None:
                parts.append(f"HDG {fmt_num(v) or '—'}°")

        elif key == "altitude":
            v = d.get("altitude")
            if v is not None:
                parts.append(f"{fmt_num(v)} ft")

        elif key == "vertical_speed":
            v = d.get("vertical_speed")
            if v is not None:
                parts.append(f"{fmt_num(v)} fpm")

        elif key == "squawk":
            v = d.get("squawk")
            if v not in (None, "", "NONE"):
                parts.append(f"SQ {v}")

    return parts


class PlaneDetailsScene(object):
    def __init__(self):
        super().__init__()
        self.plane_position = screen.WIDTH
        self._data_all_looped = False
        self.scroll_speed = 1

    @Animator.KeyFrame.add(1)
    def plane_details(self, count):
        # Optional global kill-switch
        if not SHOW_PLANE_DETAILS:
            self.draw_square(
                0,
                PLANE_DISTANCE_FROM_TOP - PLANE_TEXT_HEIGHT,
                screen.WIDTH,
                screen.HEIGHT,
                colours.BLACK,
            )
            return

        # Guard against no data
        if len(self._data) == 0:
            return

        # Build line based on current settings
        selected = load_selected_fields()
        d = self._data[self._data_index]
        parts = build_parts_for_fields(d, selected)
        full_details = " - ".join([p for p in parts if p])

        # Draw background strip
        self.draw_square(
            0,
            PLANE_DISTANCE_FROM_TOP - PLANE_TEXT_HEIGHT,
            screen.WIDTH,
            screen.HEIGHT,
            colours.BLACK,
        )

        # Draw text (empty string is fine; it just draws nothing)
        text_length = graphics.DrawText(
            self.canvas,
            PLANE_FONT,
            self.plane_position,
            PLANE_DISTANCE_FROM_TOP,
            PLANE_DETAILS_COLOUR,
            full_details,
        )

        # Scroll
        self.plane_position -= self.scroll_speed
        if self.plane_position + text_length < 0:
            self.plane_position = screen.WIDTH
            if len(self._data) > 1:
                self._data_index = (self._data_index + 1) % len(self._data)
                self._data_all_looped = (not self._data_index) or self._data_all_looped
                self.reset_scene()

    @Animator.KeyFrame.add(0)
    def reset_scrolling(self):
        self.plane_position = screen.WIDTH
