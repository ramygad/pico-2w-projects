# Pico 2W — 2.4" ST7789 TFT + EC11 Encoder + Key0 Test

import time
import board
import busio
import displayio
import digitalio
import terminalio
from fourwire import FourWire
from adafruit_st7789 import ST7789

# Release any previously configured display bus
displayio.release_displays()

# --- SPI display setup ---
# SCL=GP2, SDA(MOSI)=GP3, CS=GP4, DC=GP5, RES=GP6
spi = busio.SPI(clock=board.GP2, MOSI=board.GP3)
display_bus = FourWire(
    spi,
    command=board.GP5,      # DC
    chip_select=board.GP4,  # CS
    reset=board.GP6,        # RES
)

display = ST7789(display_bus, width=320, height=240, rotation=0)
print(f"✅ Display initialized: {display.width}x{display.height}")

# --- EC11 Rotary Encoder ---
# A=GP7, B=GP8, Push=GP9
enc_a = digitalio.DigitalInOut(board.GP7)
enc_a.direction = digitalio.Direction.INPUT
enc_a.pull = digitalio.Pull.UP

enc_b = digitalio.DigitalInOut(board.GP8)
enc_b.direction = digitalio.Direction.INPUT
enc_b.pull = digitalio.Pull.UP

enc_push = digitalio.DigitalInOut(board.GP9)
enc_push.direction = digitalio.Direction.INPUT
enc_push.pull = digitalio.Pull.UP

# --- KEY0 Button ---
key0 = digitalio.DigitalInOut(board.GP13)
key0.direction = digitalio.Direction.INPUT
key0.pull = digitalio.Pull.UP

# --- Display a test screen ---
splash = displayio.Group()

# Dark blue background
palette = displayio.Palette(1)
palette[0] = 0x000088

bg_bitmap = displayio.Bitmap(320, 240, 1)
bg = displayio.TileGrid(bg_bitmap, pixel_shader=palette)
splash.append(bg)
display.root_group = splash

# Try text label
try:
    from adafruit_display_text import label
    text_area = label.Label(
        terminalio.FONT,
        text="Pico 2W TFT Test",
        color=0xFFFFFF,
        x=80, y=30,
    )
    splash.append(text_area)
except ImportError:
    pass  # no display_text lib — show bitmap only

display.refresh()

# --- Main loop ---
last_a = enc_a.value
encoder_pos = 0
last_push = True
last_key0 = True

print("\nControls:")
print("  Turn encoder → position changes")
print("  Push encoder → toggle")
print("  KEY0 → toggle")
print()

while True:
    # --- Encoder quadrature ---
    a = enc_a.value
    b = enc_b.value
    if a != last_a:
        if b != a:
            encoder_pos += 1  # CW
        else:
            encoder_pos -= 1  # CCW
        print(f"Encoder: {encoder_pos}", end="\r")
    last_a = a

    # --- Encoder push ---
    push_val = enc_push.value
    if push_val != last_push and push_val == False:
        print(f"\n🔘 Push pressed! (pos={encoder_pos})")
    last_push = push_val

    # --- KEY0 ---
    k0 = key0.value
    if k0 != last_key0 and k0 == False:
        print(f"\n🔘 KEY0 pressed! (pos={encoder_pos})")
    last_key0 = k0

    time.sleep(0.001)
