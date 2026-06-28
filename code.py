# Wi-Fi Weather Test — Mainz, Germany
# Pico 2W CircuitPython — uses Open-Meteo API (no API key)

import time
import board
import digitalio
import wifi
import socketpool
import ssl
import adafruit_requests

# --- LED for visual feedback ---
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

def blink(n, t=0.12):
    for _ in range(n):
        led.value = True
        time.sleep(t)
        led.value = False
        time.sleep(t)

# --- Wi-Fi ---
SSID = "YOUR_SSID"
PASSWORD = "YOUR_PASSWORD_HERE"

print("\n================================================")
print("  Pico 2W — Wi-Fi Weather: Mainz, Germany")
print("================================================")
print(f"\n🔌 Connecting to \"{SSID}\"...")

try:
    wifi.radio.connect(SSID, PASSWORD)
    print(f"✅ Connected!  IP: {wifi.radio.ipv4_address}")
    blink(2, 0.15)
except Exception as e:
    print(f"❌ Wi-Fi failed: {e}")
    blink(10, 0.3)
    raise SystemExit(1)

# --- HTTP session ---
pool = socketpool.SocketPool(wifi.radio)
session = adafruit_requests.Session(pool, ssl.create_default_context())

# --- Fetch weather ---
# Open-Meteo: free, no API key, lat=49.99&lon=8.25 = Mainz, Germany
URL = (
    "https://api.open-meteo.com/v1/forecast?"
    "latitude=49.99&longitude=8.25"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
    "&daily=temperature_2m_max,temperature_2m_min,weather_code"
    "&timezone=Europe%2FBerlin"
    "&forecast_days=2"
)

# WMO weather code descriptions
WMO = {
    0: "☀️ Clear sky", 1: "🌤 Mainly clear", 2: "⛅ Partly cloudy",
    3: "☁️ Overcast", 45: "🌫 Foggy", 48: "🌫 Depositing rime fog",
    51: "🌦 Light drizzle", 53: "🌦 Moderate drizzle", 55: "🌦 Dense drizzle",
    56: "🌧 Light freezing drizzle", 57: "🌧 Dense freezing drizzle",
    61: "🌧 Slight rain", 63: "🌧 Moderate rain", 65: "🌧 Heavy rain",
    66: "🌧 Light freezing rain", 67: "🌧 Heavy freezing rain",
    71: "🌨 Slight snow", 73: "🌨 Moderate snow", 75: "🌨 Heavy snow",
    77: "❄️ Snow grains", 80: "🌦 Slight rain showers",
    81: "🌦 Moderate rain showers", 82: "🌦 Violent rain showers",
    85: "🌨 Slight snow showers", 86: "🌨 Heavy snow showers",
    95: "⛈ Thunderstorm", 96: "⛈ + slight hail", 99: "⛈ + heavy hail",
}

print(f"\n🌐 Fetching weather for Mainz, Germany...")

try:
    resp = session.get(URL)
    j = resp.json()
    resp.close()

    current = j["current"]
    daily = j["daily"]

    desc = WMO.get(current["weather_code"], f"Code {current['weather_code']}")

    print(f"\n{'─' * 44}")
    print(f"  📍  Mainz, Germany")
    print(f"  🕐  {current['time']}")
    print(f"{'─' * 44}")
    print(f"  {desc}")
    print(f"  🌡  Temperature:  {current['temperature_2m']}°C")
    print(f"  🌡  Feels like:   {current['apparent_temperature']}°C")
    print(f"  💧  Humidity:     {current['relative_humidity_2m']}%")
    print(f"  💨  Wind:         {current['wind_speed_10m']} km/h")
    print(f"{'─' * 44}")

    print(f"  📅 Forecast:")
    for i in range(len(daily["time"])):
        d = WMO.get(daily["weather_code"][i], f"Code {daily['weather_code'][i]}")
        print(f"     {daily['time'][i]}:  {daily['temperature_2m_min'][i]}–{daily['temperature_2m_max'][i]}°C  {d}")
    print(f"{'─' * 44}")

    print("\n✅ Wi-Fi + Weather test PASSED")
    blink(5, 0.12)

except Exception as e:
    print(f"\n❌ HTTP request failed: {e}")
    blink(10, 0.3)
    raise SystemExit(1)

# Keep running so user can see output
print("\n⏳ Program will auto-restart in 60 seconds...")
time.sleep(60)
