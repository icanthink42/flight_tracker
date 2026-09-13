import os, time, inspect, threading
from functools import wraps

LOG_PATH = "/home/pi/plane.drawtrace.log"
ENABLED = True  # flip to False to disable without removing import
_frame = {"n": 0}
_lock = threading.Lock()

def _scene_from_stack():
    # best-effort: find a "self" with a class name in call stack
    for f in inspect.stack():
        loc = f.frame.f_locals
        self = loc.get("self")
        if self is not None:
            return self.__class__.__name__, f.function
    return "?", "?"

def enable_drawtrace():
    if not ENABLED:
        return
    try:
        from rgbmatrix import graphics
        from rgbmatrix import RGBMatrix
    except Exception:
        return

    orig_DrawText = graphics.DrawText
    orig_SwapOnVSync = RGBMatrix.SwapOnVSync

    def log(line: str):
        with _lock:
            ts = time.strftime("%H:%M:%S")
            with open(LOG_PATH, "a", buffering=1) as f:
                f.write(f"{ts} {line}\n")

    def wrap_DrawText(canvas, font, x, y, color, text):
        cls, fn = _scene_from_stack()
        try:
            # color is an object; get rgb if available
            rgb = getattr(color, "red", None), getattr(color, "green", None), getattr(color, "blue", None)
        except Exception:
            rgb = ("?", "?", "?")
        line = f"[frame {_frame['n']:06d}] {cls}.{fn} DrawText ({x},{y}) rgb={rgb} text={text!r}"
        log(line)
        return orig_DrawText(canvas, font, x, y, color, text)

    def wrap_SwapOnVSync(self, *a, **kw):
        try:
            _frame["n"] += 1
        except Exception:
            pass
        return orig_SwapOnVSync(self, *a, **kw)

    graphics.DrawText = wrap_DrawText
    RGBMatrix.SwapOnVSync = wrap_SwapOnVSync

