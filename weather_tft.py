# Pico 2W — Weather Forecast on ST7789 TFT (v3 — Multi-City)
# ================================================================
# Connects to Wi-Fi, fetches Open-Meteo weather for multiple cities,
# displayed on 2.4" 320x240 ST7789 TFT.
#
# Features:
#   - EC11 rotary encoder to switch between cities
#   - Audio feedback via GY-PCM5102 DAC on GPIO10/11/12
#   - Cities: Mainz (DE), Alexandria (EG), Cairo (EG), Amsterdam (NL)
#   - Current: temp, feels-like, humidity, wind, UV, pressure
#   - 6-hour hourly forecast bar chart with temp-colored bars
#   - Sunrise/sunset times
#   - 2-day daily forecast with rain probability
#   - Temperature-based color coding
#   - Day/night indicator
#   - Auto-refresh every 5 minutes or on encoder push
#
# Pinout:
#   TFT:   SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6
#   EC11:   A=GP7,  B=GP8,   Push=GP9
#   I2S:   BCK=GP10, LCK=GP11, DIN=GP12  (GY-PCM5102 DAC)
#
# Dependencies (copy to CIRCUITPY):
#   adafruit_st7789.py  ->  /lib/
#   adafruit_display_text/  ->  /lib/  (entire folder)
#   adafruit_requests.mpy  ->  /lib/
#   adafruit_connection_manager.mpy  ->  /lib/
#   wifi_config.py  ->  / (root, gitignored)
# ================================================================

import time
import board
import busio
import displayio
import terminalio
import digitalio
import audiobusio
import audiocore
import array
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

ENC_A    = board.GP7
ENC_B    = board.GP8
ENC_PUSH = board.GP9

WIDTH  = 320
HEIGHT = 240

# ── Colours ─────────────────────────────────────────────────────────────
WHITE  = 0xFFFFFF
CYAN   = 0x00FFFF
YELLOW = 0xFFDD00
ORANGE = 0xFF8800
GRAY   = 0x888888
GREEN  = 0x00FF00
RED    = 0xFF4444
BLUE   = 0x4488FF

# ── Cities ───────────────────────────────────────────────────────────────
CITIES = [
    {"name": "Mainz, Germany",        "lat": 49.99, "lon": 8.25,  "tz": "Europe/Berlin"},
    {"name": "Alexandria, Egypt",     "lat": 31.20, "lon": 29.92, "tz": "Africa/Cairo"},
    {"name": "Cairo, Egypt",          "lat": 30.04, "lon": 31.24, "tz": "Africa/Cairo"},
    {"name": "Amsterdam, Netherlands", "lat": 52.37, "lon": 4.90,  "tz": "Europe/Amsterdam"},
]
N_CITIES = len(CITIES)
current_city = 0

# ── WMO weather-code descriptions ───────────────────────────────────────
WMO = {
    0: "Clear sky",       1: "Mainly clear",    2: "Partly cloudy",
    3: "Overcast",        45: "Foggy",           48: "Rime fog",
    51: "Light drizzle",  53: "Mod drizzle",     55: "Dense drizzle",
    61: "Light rain",     63: "Moderate rain",   65: "Heavy rain",
    71: "Light snow",     73: "Moderate snow",   75: "Heavy snow",
    80: "Light showers",  81: "Mod showers",     82: "Heavy showers",
    95: "Thunderstorm",   96: "T-storm + hail",  99: "Heavy T-storm",
}

WMO_SHORT = {
    0: "Clear",  1: "M.Clr", 2: "P.Cld", 3: "Ocast",
    45: "Fog",   48: "Fog",
    51: "L.Drz", 53: "M.Drz", 55: "D.Drz",
    61: "L.Rn",  63: "M.Rn",  65: "H.Rn",
    71: "L.Sn",  73: "M.Sn",  75: "H.Sn",
    80: "L.Sh",  81: "M.Sh",  82: "H.Sh",
    95: "T.St",  96: "T.Hl", 99: "H.T.St",
}

def temp_color(t):
    """Color-code temperature: cold=blue, mild=green, warm=yellow, hot=orange."""
    if t < 0:   return BLUE
    if t < 10:  return CYAN
    if t < 20:  return GREEN
    if t < 28:  return YELLOW
    return ORANGE

def make_bar(x, y, w, h, color):
    """Create a filled rectangle as a TileGrid."""
    bmp = displayio.Bitmap(max(1, w), max(1, h), 1)
    pal = displayio.Palette(1)
    pal[0] = color
    return displayio.TileGrid(bmp, pixel_shader=pal, x=x, y=y)

# ══════════════════════════════════════════════════════════════════════
#  1. Initialise TFT Display
# ══════════════════════════════════════════════════════════════════════
print("Init TFT...")
displayio.release_displays()
spi = busio.SPI(clock=TFT_SCK, MOSI=TFT_MOSI)
display_bus = FourWire(spi, command=TFT_DC, chip_select=TFT_CS, reset=TFT_RES)
display = ST7789(display_bus, width=WIDTH, height=HEIGHT, rotation=270)

# ══════════════════════════════════════════════════════════════════════
#  2. Initialise EC11 Encoder
# ══════════════════════════════════════════════════════════════════════
enc_a = digitalio.DigitalInOut(ENC_A)
enc_a.direction = digitalio.Direction.INPUT
enc_a.pull = digitalio.Pull.UP

enc_b = digitalio.DigitalInOut(ENC_B)
enc_b.direction = digitalio.Direction.INPUT
enc_b.pull = digitalio.Pull.UP

enc_push = digitalio.DigitalInOut(ENC_PUSH)
enc_push.direction = digitalio.Direction.INPUT
enc_push.pull = digitalio.Pull.UP

print("Encoder ready (A=GP7, B=GP8, Push=GP9)")

# Encoder state — quadrature state machine with transition table
# EC11 has 2 full quadrature cycles per detent click.
# States based on (A,B): 00=0, 01=1, 11=2, 10=3

# Direction lookup: (from_state, to_state) -> 1=CW, -1=CCW
TRANS_TABLE = {
    (0, 1): 1,   (0, 2): -1,
    (1, 0): -1,  (1, 3): 1,
    (2, 0): 1,   (2, 3): -1,
    (3, 1): -1,  (3, 2): 1,
}

enc_state = (enc_a.value << 1) | enc_b.value
enc_last_state = enc_state
enc_counter = 0  # accumulates direction; emit event at |count| >= 4
enc_push_prev = enc_push.value
last_push_time = 0
last_rot_time = 0
ROT_DEBOUNCE = 0.01   # 10ms — quadrature table already rejects noise

# Raw transition counter for speed detection
raw_transition_count = 0
last_speed_check = 0
TRANS_RATE_BINS = [(12, 1), (32, 2), (60, N_CITIES), (120, N_CITIES), (99999, N_CITIES)]

def read_encoder():
    """Poll EC11 encoder using quadrature transition table.
    Returns -1 (CCW), +1 (CW), 0 (no movement), 99 (push)."""
    global enc_last_state, enc_counter, enc_push_prev, last_push_time, last_rot_time

    now = time.monotonic()

    # ── Rotation detection (transition table) ────────────────────────
    a_val = enc_a.value
    b_val = enc_b.value
    cur_state = (a_val << 1) | b_val

    if cur_state != enc_last_state:
        key = (enc_last_state, cur_state)
        direction = TRANS_TABLE.get(key, 0)
        enc_last_state = cur_state
        if direction != 0:
            enc_counter += direction
            raw_transition_count += 1
            if abs(enc_counter) >= 4:
                enc_counter = 0
                if (now - last_rot_time) > ROT_DEBOUNCE:
                    last_rot_time = now
                    return direction  # 1=CW, -1=CCW

    # ── Push button detection (debounced) ──────────────────────────
    push_val = enc_push.value
    if push_val != enc_push_prev:
        enc_push_prev = push_val
        if not push_val:  # pressed (pulled low)
            if now - last_push_time > 0.3:
                last_push_time = now
                return 99

    return 0

# ══════════════════════════════════════════════════════════════════════
#  2b. Initialise I2S Audio (GY-PCM5102 DAC)
# ══════════════════════════════════════════════════════════════════════
# Pinout: BCK=GP10, LCK=GP11, DIN=GP12
I2S_BCK = board.GP10
I2S_LCK = board.GP11
I2S_DIN = board.GP12

SAMPLE_RATE = 16000
AUDIO_VOL   = 0.25

audio_i2s = None
try:
    audio_i2s = audiobusio.I2SOut(I2S_BCK, I2S_LCK, I2S_DIN)
    print(f"I2S audio ready ({SAMPLE_RATE} Hz, vol={AUDIO_VOL})")
except Exception as e:
    print(f"I2S audio init skipped: {e}")

def make_tone(freq_hz, duration_s, vol=AUDIO_VOL):
    """Create a square-wave RawSample at given frequency and duration."""
    n = int(SAMPLE_RATE * duration_s)
    period = max(2, int(SAMPLE_RATE / freq_hz))
    half = period // 2
    samples = array.array('h', [0]) * n
    for i in range(n):
        if (i % period) < half:
            samples[i] = int(32767 * vol)
        else:
            samples[i] = -int(32767 * vol)
    return audiocore.RawSample(samples, sample_rate=SAMPLE_RATE)

# Pre-compute feedback tones (small — <256 bytes each)
BEEP_CW   = make_tone(1200, 0.10)   # CW: short higher-pitch "up"
BEEP_CCW  = make_tone(600, 0.10)    # CCW: short lower-pitch "down"
BEEP_PUSH = make_tone(880, 0.15)    # Push: medium beep

def play_beep(tone):
    """Play a pre-computed tone if audio is available (non-blocking, returns fast)."""
    if audio_i2s is not None:
        try:
            audio_i2s.play(tone, loop=False)
        except Exception as e:
            print(f"Audio error: {e}")

# ══════════════════════════════════════════════════════════════════════
#  3. Build UI Layout
# ══════════════════════════════════════════════════════════════════════

def make_label(text, x, y, color=WHITE, scale=1):
    return label.Label(terminalio.FONT, text=text, color=color, x=x, y=y, scale=scale)

main_group = displayio.Group()

# ── Status bar (Wi-Fi status, time, day/night) ─────────────────────────
status_bar = make_label("", 0, 0, GRAY, scale=1)
main_group.append(status_bar)

# ── City selector hint (top right) ──────────────────────────────────────
city_hint = make_label("< turn >", 250, 0, GRAY, scale=1)
main_group.append(city_hint)

# ── Title (city name) ───────────────────────────────────────────────────
title = make_label(CITIES[0]["name"], 5, 18, CYAN, scale=2)
main_group.append(title)

# ── Big temperature + condition ─────────────────────────────────────────
temp_text = make_label("--", 5, 44, YELLOW, scale=3)
main_group.append(temp_text)

cond_text = make_label("--", 120, 48, WHITE, scale=2)
main_group.append(cond_text)

# ── Details line 1 (feels, hum, wind, UV, pressure) ────────────────────
details1 = make_label("", 5, 78, WHITE, scale=1)
main_group.append(details1)

# ── Details line 2 (sunrise, sunset, rain) ─────────────────────────────
details2 = make_label("", 5, 92, GRAY, scale=1)
main_group.append(details2)

# ── Hourly forecast header ──────────────────────────────────────────────
hourly_hdr = make_label("--- 6-Hour Forecast ---", 80, 108, GRAY, scale=1)
main_group.append(hourly_hdr)

# ── Hour labels (above bars) ────────────────────────────────────────────
N_HOURS = 6
hour_labels = []
for i in range(N_HOURS):
    hl = make_label("--:--", 0, 120, GRAY, scale=1)
    main_group.append(hl)
    hour_labels.append(hl)

# ── Bar chart group (bars added/removed dynamically) ────────────────────
chart_group = displayio.Group()
main_group.append(chart_group)

# ── Temp labels (below bars) ─────────────────────────────────────────────
temp_labels = []
for i in range(N_HOURS):
    tl = make_label("--", 0, 178, YELLOW, scale=1)
    main_group.append(tl)
    temp_labels.append(tl)

# ── Condition labels (below temp) ───────────────────────────────────────
cond_labels = []
for i in range(N_HOURS):
    cl = make_label("--", 0, 192, GRAY, scale=1)
    main_group.append(cl)
    cond_labels.append(cl)

# ── Daily forecast ───────────────────────────────────────────────────────
today_text = make_label("Today:  --", 5, 207, ORANGE, scale=2)
tomrw_text = make_label("Tomrw:  --", 5, 225, ORANGE, scale=2)
main_group.append(today_text)
main_group.append(tomrw_text)

display.root_group = main_group
print("TFT ready.")

# ══════════════════════════════════════════════════════════════════════
#  4. Wi-Fi + Weather
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

def build_url(city):
    """Build Open-Meteo URL for a city."""
    tz_enc = city["tz"].replace("/", "%2F")
    return (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={city['lat']}&longitude={city['lon']}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "weather_code,wind_speed_10m,is_day,uv_index,pressure_msl"
        "&hourly=temperature_2m,weather_code,precipitation_probability"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code,"
        "sunrise,sunset,uv_index_max,precipitation_probability_max"
        f"&timezone={tz_enc}"
        "&forecast_days=2"
    )

# Bar chart geometry
BAR_W       = 30
BAR_GAP     = 8
BAR_TOP     = 132
BAR_BOTTOM  = 172
BAR_MAX_H   = BAR_BOTTOM - BAR_TOP   # 40px
BAR_START_X = 50

def update_bars(temps):
    """Rebuild the hourly temperature bar chart."""
    while len(chart_group) > 0:
        chart_group.pop()
    if not temps:
        return
    tmin = min(temps)
    tmax = max(temps)
    trange = max(1.0, tmax - tmin)
    for i, t in enumerate(temps):
        h = int((t - tmin) / trange * (BAR_MAX_H - 6) + 4)
        h = max(4, min(BAR_MAX_H, h))
        x = BAR_START_X + i * (BAR_W + BAR_GAP)
        y = BAR_BOTTOM - h
        bar = make_bar(x, y, BAR_W, h, temp_color(t))
        chart_group.append(bar)

def update_weather(city_idx):
    """Fetch weather from Open-Meteo for the given city and update display."""
    city = CITIES[city_idx]
    print(f"Fetching weather for {city['name']}...")
    status_bar.text = f"Updating {city['name'][:12]}..."
    title.text = city["name"]
    try:
        url = build_url(city)
        resp = session.get(url)
        j = resp.json()
        resp.close()

        cur    = j["current"]
        daily  = j["daily"]
        hourly = j["hourly"]

        # ── Current conditions ─────────────────────────────────────
        code = cur["weather_code"]
        desc = WMO.get(code, f"Code {code}")
        cond_text.text = desc

        temp = cur["temperature_2m"]
        temp_text.text = f"{temp:.0f}\xb0C"
        temp_text.color = temp_color(temp)

        feels = cur["apparent_temperature"]
        hum   = cur["relative_humidity_2m"]
        wind  = cur["wind_speed_10m"]
        uv    = cur["uv_index"]
        press = cur["pressure_msl"]
        details1.text = (
            f"Feels:{feels:.0f}\xb0C  Hum:{hum}%  Wind:{wind:.0f}km/h"
            f"  UV:{uv:.1f}  {press:.0f}hPa"
        )

        # ── Sun + rain info ────────────────────────────────────────
        sunrise = daily["sunrise"][0][-5:]   # "05:30"
        sunset  = daily["sunset"][0][-5:]    # "21:34"
        rain0   = daily["precipitation_probability_max"][0]
        details2.text = f"Sunrise {sunrise}  Sunset {sunset}  Rain:{rain0}%"

        # ── Hourly forecast (next 6 hours from current time) ───────
        current_time = cur["time"]
        hour_list    = hourly["time"]

        start_idx = 0
        for i, ht in enumerate(hour_list):
            if ht >= current_time:
                start_idx = i
                break

        n = min(N_HOURS, len(hour_list) - start_idx)
        temps_hourly = []
        for i in range(n):
            idx = start_idx + i
            t = hourly["temperature_2m"][idx]
            c = hourly["weather_code"][idx]
            h_time = hour_list[idx][-5:]

            temps_hourly.append(t)
            x = BAR_START_X + i * (BAR_W + BAR_GAP)

            hour_labels[i].text = h_time
            hour_labels[i].x = x + 2

            temp_labels[i].text = f"{t:.0f}\xb0"
            temp_labels[i].color = temp_color(t)
            temp_labels[i].x = x + 4

            cond_labels[i].text = WMO_SHORT.get(c, "?")
            cond_labels[i].x = x + 2

        for i in range(n, N_HOURS):
            hour_labels[i].text = ""
            temp_labels[i].text = ""
            cond_labels[i].text = ""

        update_bars(temps_hourly)

        # ── Daily forecast ──────────────────────────────────────────
        t_min0 = daily["temperature_2m_min"][0]
        t_max0 = daily["temperature_2m_max"][0]
        rain0  = daily["precipitation_probability_max"][0]
        today_text.text = f"Today:  {t_min0:.0f}-{t_max0:.0f}\xb0C  Rain:{rain0}%"

        t_min1 = daily["temperature_2m_min"][1]
        t_max1 = daily["temperature_2m_max"][1]
        rain1  = daily["precipitation_probability_max"][1]
        tomrw_text.text = f"Tomrw:  {t_min1:.0f}-{t_max1:.0f}\xb0C  Rain:{rain1}%"

        # ── Status bar ─────────────────────────────────────────────
        is_day  = cur.get("is_day", 1)
        time_str = current_time[-5:]
        city_short = city["name"].split(",")[0]
        status_bar.text = f"WiFi OK  {city_short} {time_str}  {'Day' if is_day else 'Night'}"

        print("Display updated.")
        return True

    except Exception as e:
        print(f"Fetch error: {e}")
        status_bar.text = "Error!"
        cond_text.text = "Connection"
        temp_text.text = "FAIL"
        return False

# ══════════════════════════════════════════════════════════════════════
#  5. Main loop — encoder polling + auto-refresh
# ══════════════════════════════════════════════════════════════════════
print("Starting main loop. Turn encoder to switch cities, push to refresh.")

# Initial weather fetch
update_weather(current_city)

REFRESH_SEC = 300  # 5 minutes auto-refresh
last_refresh = time.monotonic()

# Speed-aware rotation for city switching — uses raw transition rate
last_rot_event = 0

def city_step():
    """Return number of cities to skip based on raw transition rate."""
    global last_rot_event, last_speed_check, raw_transition_count
    now = time.monotonic()
    dt = now - last_speed_check
    count = raw_transition_count
    raw_transition_count = 0
    last_speed_check = now

    if count < 4 or dt <= 0:
        return 1

    rate = count / dt
    for threshold, skip in TRANS_RATE_BINS:
        if rate <= threshold:
            return skip
    return N_CITIES

while True:
    # Poll encoder (non-blocking, fast)
    enc = read_encoder()

    if enc == 1:  # CW — next city
        s = city_step()
        play_beep(BEEP_CW)
        current_city = (current_city + s) % N_CITIES
        print(f"Switching to city {current_city}: {CITIES[current_city]['name']}  (speed={s})")
        update_weather(current_city)
        last_refresh = time.monotonic()

    elif enc == -1:  # CCW — previous city
        s = city_step()
        play_beep(BEEP_CCW)
        current_city = (current_city - s) % N_CITIES
        print(f"Switching to city {current_city}: {CITIES[current_city]['name']}  (speed={s})")
        update_weather(current_city)
        last_refresh = time.monotonic()

    elif enc == 99:  # Push — force refresh
        play_beep(BEEP_PUSH)
        print("Push button — refreshing current city")
        update_weather(current_city)
        last_refresh = time.monotonic()

    # Auto-refresh check
    if time.monotonic() - last_refresh >= REFRESH_SEC:
        update_weather(current_city)
        last_refresh = time.monotonic()

    time.sleep(0.01)  # Small delay to avoid busy-spin
