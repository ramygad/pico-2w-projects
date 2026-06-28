# Pico 2W — Weather Forecast on ST7789 TFT
# ================================================
# Connects to Wi-Fi, fetches Open-Meteo weather
# for Mainz, Germany, and displays on the 2.4"
# 320x240 ST7789 TFT display.
#
# Pinout: SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6
#
# Dependencies (copy to CIRCUITPY):
#   adafruit_st7789.py  →  /lib/
#   adafruit_display_text/  →  /lib/  (entire folder)
#   wifi_config.py      →  / (root, gitignored)
#
# Deploy:
#   cp weather_tft.py /d/code.py     (Windows cmd)
#   cp adafruit_st7789.py /d/lib/
#   cp -r adafruit_display_text /d/lib/
#   cp wifi_config.py /d/
# ================================================

import time
import board
import busio
import displayio
import terminalio
import wifi
import socketpool
import ssl
import adafruit_requests
from fourwire import FourWire
from adafruit_st7789 import ST7789
from adafruit_display_text import label
import wifi_config

# ── Pin Assignments ────────────────────────────────────────────────────
TFT_SCK  = board.GP2
TFT_MOSI = board.GP3
TFT_CS   = board.GP4
TFT_DC   = board.GP5
TFT_RES  = board.GP6

WIDTH  = 320
HEIGHT = 240

# ── Colours ────────────────────────────────────────────────────────────
WHITE   = 0xFFFFFF
CYAN    = 0x00FFFF
YELLOW  = 0xFFDD00
ORANGE  = 0xFF8800
GRAY    = 0x888888
DARK_BG = 0x0A1628  # dark navy background

# ── WMO weather-code descriptions ──────────────────────────────────────
WMO = {
    0: "Clear sky",       1: "Mainly clear",    2: "Partly cloudy",
    3: "Overcast",        45: "Foggy",           48: "Rime fog",
    51: "Light drizzle",  53: "Mod drizzle",     55: "Dense drizzle",
    61: "Light rain",     63: "Moderate rain",   65: "Heavy rain",
    71: "Light snow",     73: "Moderate snow",   75: "Heavy snow",
    80: "Light showers",  81: "Mod showers",     82: "Heavy showers",
    95: "Thunderstorm",   96: "T-storm + hail",  99: "Heavy T-storm + hail",
}

# ── Emoji / icon map for weather codes ─────────────────────────────────
WMO_ICON = {
    0: "\ue24e", 1: "\ue312", 2: "\ue313",
    3: "\ue312", 45: "\ue313", 48: "\ue313",
    51: "\ue318", 53: "\ue318", 55: "\ue318",
    61: "\ue318", 63: "\ue318", 65: "\ue318",
    71: "\ue31a", 73: "\ue31a", 75: "\ue31a",
    80: "\ue318", 81: "\ue318", 82: "\ue318",
    95: "\ue31d", 96: "\ue31d", 99: "\ue31d",
}

# WMO_ICON dictionary has hex escape sequences that may not render.
# We'll use text descriptions instead, so the WMO_ICON map is decorative.
# Replaced with simple ASCII markers below.

# ══════════════════════════════════════════════════════════════════════
#  1. Initialise TFT Display
# ══════════════════════════════════════════════════════════════════════
print("Init TFT...")
displayio.release_displays()
spi = busio.SPI(clock=TFT_SCK, MOSI=TFT_MOSI)
display_bus = FourWire(spi, command=TFT_DC, chip_select=TFT_CS, reset=TFT_RES)

# rotation=270 gives landscape with USB connector on left
# (adjust to 90 if text appears upside-down)
display = ST7789(display_bus, width=WIDTH, height=HEIGHT, rotation=270)

# ══════════════════════════════════════════════════════════════════════
#  2. Build UI Layout
# ══════════════════════════════════════════════════════════════════════

def make_label(text, x, y, color=WHITE, scale=1):
    """Create a display text label."""
    return label.Label(terminalio.FONT, text=text, color=color, x=x, y=y, scale=scale)

main_group = displayio.Group()

# ── Status bar (Wi-Fi, refresh) ────────────────────────────────────────
status_bar = make_label("", 0, 0, GRAY, scale=1)
main_group.append(status_bar)

# ── Title ──────────────────────────────────────────────────────────────
title = make_label("Mainz, Germany", WIDTH // 2 - 70, 22, CYAN, scale=2)
main_group.append(title)

# ── Main weather icon / condition area ─────────────────────────────────
cond_text = make_label("--", 10, 52, WHITE, scale=3)
main_group.append(cond_text)

# Temperature (large, prominent)
temp_text = make_label("--", 10, 88, YELLOW, scale=3)
main_group.append(temp_text)

# ── Details (vertical stack, bigger text) ──────────────────────────────
feels_text  = make_label("Feels: --",        10, 130, WHITE, scale=2)
humid_text  = make_label("Humidity: --",     10, 152, WHITE, scale=2)
wind_text   = make_label("Wind: --",         10, 174, WHITE, scale=2)
main_group.append(feels_text)
main_group.append(humid_text)
main_group.append(wind_text)

# ── Forecast ───────────────────────────────────────────────────────────
today_text     = make_label("Today:  --",    10, 205, ORANGE, scale=2)
tomorrow_text  = make_label("Tomrw:  --",    10, 225, ORANGE, scale=2)
main_group.append(today_text)
main_group.append(tomorrow_text)

display.root_group = main_group
print("TFT ready.")

# ══════════════════════════════════════════════════════════════════════
#  3. Wi-Fi + Weather
# ══════════════════════════════════════════════════════════════════════
print("Connecting to Wi-Fi...")
status_bar.text = "Wi-Fi..."
wifi_ok = False
for attempt in range(5):
    try:
        wifi.radio.connect(wifi_config.SSID, wifi_config.PASSWORD)
        print(f"OK: {wifi.radio.ipv4_address}")
        status_bar.text = f"WiFi  {wifi.radio.ipv4_address}"
        wifi_ok = True
        break
    except Exception as e:
        print(f"Wi-Fi attempt {attempt+1}: {e}")
        status_bar.text = f"WiFi try {attempt+1}"
        time.sleep(2)

if not wifi_ok:
    print("Wi-Fi failed after 5 attempts")
    status_bar.text = "Wi-Fi FAIL"

pool = socketpool.SocketPool(wifi.radio)
session = adafruit_requests.Session(pool, ssl.create_default_context())

URL = (
    "https://api.open-meteo.com/v1/forecast?"
    "latitude=49.99&longitude=8.25"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
    "&daily=temperature_2m_max,temperature_2m_min,weather_code"
    "&timezone=Europe%2FBerlin"
    "&forecast_days=2"
)

def update_weather():
    """Fetch weather from Open-Meteo and update all display labels."""
    print("Fetching weather...")
    status_bar.text = "Updating..."
    try:
        resp = session.get(URL)
        j = resp.json()
        resp.close()

        cur = j["current"]
        daily = j["daily"]

        # ── Current conditions ──────────────────────────
        code = cur["weather_code"]
        desc = WMO.get(code, f"Code {code}")
        cond_text.text = desc

        temp = cur["temperature_2m"]
        temp_text.text = f"{temp:.0f}\xb0C"   # \xb0 = degree symbol

        feels = cur["apparent_temperature"]
        feels_text.text = f"Feels: {feels:.0f}\xb0C"

        hum = cur["relative_humidity_2m"]
        humid_text.text = f"Humidity: {hum}%"

        wind = cur["wind_speed_10m"]
        wind_text.text = f"Wind: {wind:.0f} km/h"

        # ── Daily forecast ──────────────────────────────
        t_min0 = daily["temperature_2m_min"][0]
        t_max0 = daily["temperature_2m_max"][0]
        today_text.text = f"Today:  {t_min0:.0f}-{t_max0:.0f}\xb0C"

        t_min1 = daily["temperature_2m_min"][1]
        t_max1 = daily["temperature_2m_max"][1]
        code1  = daily["weather_code"][1]
        desc1  = WMO.get(code1, f"Code {code1}")
        tomorrow_text.text = f"Tomrw:  {t_min1:.0f}-{t_max1:.0f}\xb0C"

        status_bar.text = f"WiFi  OK  {cur['time'][-5:]}"
        print("Display updated.")
        return True

    except Exception as e:
        print(f"Fetch error: {e}")
        status_bar.text = "Error!"
        cond_text.text = "Connection"
        temp_text.text = "FAIL"
        feels_text.text = str(e)[:30]
        return False

# ══════════════════════════════════════════════════════════════════════
#  4. Initial fetch + Main loop
# ══════════════════════════════════════════════════════════════════════
update_weather()

while True:
    for _ in range(300):   # ~5 minutes (300 x ~1s sleep)
        time.sleep(1)
    update_weather()
