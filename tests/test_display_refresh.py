"""Test refresh behavior without importing the Pi-only RGB matrix library."""

import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


DISPLAY_SOURCE = Path(__file__).resolve().parents[1] / "display" / "__init__.py"


def load_display_method(name):
    module = ast.parse(DISPLAY_SOURCE.read_text())
    display = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Display")
    method = next(node for node in display.body if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    code = compile(ast.Module(body=[method], type_ignores=[]), str(DISPLAY_SOURCE), "exec")
    namespace = {
        "callsigns_match": lambda a, b: {f["callsign"] for f in a} == {f["callsign"] for f in b},
    }
    exec(code, namespace)
    return namespace[name]


class DisplayRefreshTests(unittest.TestCase):
    def test_fetches_again_even_when_multiple_planes_have_not_scrolled(self):
        display = Mock()
        display._data = [{"callsign": "ONE"}, {"callsign": "TWO"}]
        display._data_all_looped = False
        display.overhead.processing = False
        load_display_method("grab_new_data")(display, 0)
        display.overhead.grab_data.assert_called_once_with()

    def test_updates_telemetry_without_resetting_scene(self):
        display = Mock()
        display._data = [{"callsign": "ONE", "altitude": 1000}]
        display.overhead.new_data = True
        display.overhead.data_is_empty = False
        display.overhead.data = [{"callsign": "ONE", "altitude": 2000}]
        load_display_method("check_for_loaded_data")(display, 0)
        self.assertEqual(display._data[0]["altitude"], 2000)
        display.reset_scene.assert_not_called()


if __name__ == "__main__":
    unittest.main()
