"""Draw a static message on the 64x32 plane-spotter LED matrix."""

import os
import signal
import time

from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics


WIDTH = 64
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "5x8.bdf")


def create_matrix():
    """Configure the panel using the settings from the reference application."""
    try:
        from config import BRIGHTNESS, GPIO_SLOWDOWN, HAT_PWM_ENABLED
    except (ImportError, NameError):
        BRIGHTNESS = 100
        GPIO_SLOWDOWN = 1
        HAT_PWM_ENABLED = True

    options = RGBMatrixOptions()
    options.hardware_mapping = (
        "adafruit-hat-pwm" if HAT_PWM_ENABLED else "adafruit-hat"
    )
    options.rows = 32
    options.cols = WIDTH
    options.chain_length = 1
    options.parallel = 1
    options.row_address_type = 0
    options.multiplexing = 0
    options.pwm_bits = 8
    options.brightness = BRIGHTNESS
    options.pwm_lsb_nanoseconds = 180
    options.led_rgb_sequence = "RGB"
    options.pixel_mapper_config = ""
    options.show_refresh_rate = 0
    options.gpio_slowdown = GPIO_SLOWDOWN
    options.disable_hardware_pulsing = True
    options.drop_privileges = True
    return RGBMatrix(options=options)


def draw_centered(canvas, font, y, colour, text):
    # The 5x8 BDF font advances six pixels for each character.
    text_width = len(text) * 6
    x = max(0, (WIDTH - text_width) // 2)
    graphics.DrawText(canvas, font, x, y, colour, text)


def main():
    matrix = create_matrix()
    canvas = matrix.CreateFrameCanvas()
    canvas.Clear()

    font = graphics.Font()
    font.LoadFont(FONT_PATH)
    draw_centered(canvas, font, 12, graphics.Color(0, 180, 255), "hacked by")
    draw_centered(canvas, font, 25, graphics.Color(0, 255, 90), "neelemanet")
    canvas = matrix.SwapOnVSync(canvas)

    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while running:
        time.sleep(1)

    canvas.Clear()
    matrix.SwapOnVSync(canvas)


if __name__ == "__main__":
    main()
