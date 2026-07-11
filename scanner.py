# Pico 2W — Wi-Fi + BLE Scanner
# ================================================================
# Scans for available Wi-Fi networks and Bluetooth (BLE) devices.
# UI via ST7789 TFT + EC11 encoder.
#
# Features:
#   - Wi-Fi scan: SSID, RSSI, signal bar, auth type
#   - BLE scan: device name, RSSI, address
#   - Toggle between Wi-Fi/BLE mode via encoder push
#   - Scoll through results via encoder turn
#   - KEY0: trigger fresh scan
#
# Pinout:
#   TFT:   SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6
#   EC11:  A=GP7, B=GP8, Push=GP9
#   KEY0:  GP13
# ================================================================

import time
import board
import busio
import displayio
import terminalio
import digitalio
import wifi
from fourwire import FourWire
from adafruit_st7789 import ST7789
from adafruit_display_text import label

# Try to import BLE (may not be available on all builds)
_bleio = None
try:
    import _bleio
    # Check if BLE adapter is available
    _bleio.adapter
    # Quick test - can we start/stop?
    _bleio.adapter.start_scan(timeout=0.1)
    _bleio.adapter.stop_scan()
except Exception as e:
    print(f"BLE not available: {e}")
    _bleio = None

# ── Pin Assignments ────────────────────────────────────────────────────
TFT_SCK  = board.GP2
TFT_MOSI = board.GP3
TFT_CS   = board.GP4
TFT_DC   = board.GP5
TFT_RES  = board.GP6

ENC_A    = board.GP7
ENC_B    = board.GP8
ENC_PUSH = board.GP9
KEY0     = board.GP13

WIDTH  = 320
HEIGHT = 240

# ── Colours ─────────────────────────────────────────────────────────────
WHITE    = 0xFFFFFF
CYAN     = 0x00FFFF
YELLOW   = 0xFFDD00
GREEN    = 0x00FF00
ORANGE   = 0xFF8800
GRAY     = 0x888888
DIM_GRAY = 0x444444
RED      = 0xFF4444
BLUE     = 0x4488FF

# ── State ────────────────────────────────────────────────────────────────
mode = "wifi"  # "wifi" or "ble"
scan_results = []
scroll_pos = 0
max_visible = 12  # items visible on screen
scanning = False

# ── Wi-Fi auth mode names ──────────────────────────────────────────────
AUTH_NAMES = {
    0: "Open", 1: "WEP", 2: "WPA/PSK",
    3: "WPA2/PSK", 4: "WPA/WPA2", 5: "WPA2/Ent",
    6: "WPA3/PSK", 7: "WPA2/WPA3",
}

# ══════════════════════════════════════════════════════════════════════
#  1. Init TFT Display
# ══════════════════════════════════════════════════════════════════════
print("Init TFT...")
displayio.release_displays()
spi = busio.SPI(clock=TFT_SCK, MOSI=TFT_MOSI)
display_bus = FourWire(spi, command=TFT_DC, chip_select=TFT_CS, reset=TFT_RES)
display = ST7789(display_bus, width=WIDTH, height=HEIGHT, rotation=270)

# ══════════════════════════════════════════════════════════════════════
#  2. Init Encoder + KEY0
# ══════════════════════════════════════════════════════════════════════
print("Init encoder...")
enc_a = digitalio.DigitalInOut(ENC_A)
enc_a.direction = digitalio.Direction.INPUT
enc_a.pull = digitalio.Pull.UP

enc_b = digitalio.DigitalInOut(ENC_B)
enc_b.direction = digitalio.Direction.INPUT
enc_b.pull = digitalio.Pull.UP

enc_push = digitalio.DigitalInOut(ENC_PUSH)
enc_push.direction = digitalio.Direction.INPUT
enc_push.pull = digitalio.Pull.UP

key0 = digitalio.DigitalInOut(KEY0)
key0.direction = digitalio.Direction.INPUT
key0.pull = digitalio.Pull.UP

# Quadrature decoder
TRANS_TABLE = {
    (0, 1): 1,   (0, 2): -1,
    (1, 0): -1,  (1, 3): 1,
    (2, 0): 1,   (2, 3): -1,
    (3, 1): -1,  (3, 2): 1,
}
enc_s = (enc_a.value << 1) | enc_b.value
enc_last_s = enc_s
enc_cnt = 0
enc_push_prev = enc_push.value
key0_prev = key0.value
last_rot_t = 0
last_push_t = 0
last_key0_t = 0
ROT_DEBOUNCE = 0.01
PUSH_DEBOUNCE = 0.3

def read_enc():
    global enc_last_s, enc_cnt, enc_push_prev, key0_prev
    global last_rot_t, last_push_t, last_key0_t
    now = time.monotonic()
    a, b = enc_a.value, enc_b.value
    cs = (a << 1) | b
    if cs != enc_last_s:
        d = TRANS_TABLE.get((enc_last_s, cs), 0)
        enc_last_s = cs
        if d:
            enc_cnt += d
            if abs(enc_cnt) >= 4:
                enc_cnt = 0
                if (now - last_rot_t) > ROT_DEBOUNCE:
                    last_rot_t = now
                    return d
    pv = enc_push.value
    if pv != enc_push_prev:
        enc_push_prev = pv
        if not pv and (now - last_push_t) > PUSH_DEBOUNCE:
            last_push_t = now
            return 99
    k0 = key0.value
    if k0 != key0_prev:
        key0_prev = k0
        if not k0 and (now - last_key0_t) > PUSH_DEBOUNCE:
            last_key0_t = now
            return 98
    return 0

# ══════════════════════════════════════════════════════════════════════
#  3. Build UI Layout
# ══════════════════════════════════════════════════════════════════════

def L(text, x, y, color=WHITE, scale=1):
    return label.Label(terminalio.FONT, text=text, color=color, x=x, y=y, scale=scale)

g = displayio.Group()

# Title bar
title = L("SCANNER", 5, 4, CYAN, scale=2)
g.append(title)

# Mode indicator
mode_label = L("Wi-Fi", 210, 6, GREEN, scale=1)
g.append(mode_label)

# Status / count line
status_label = L("", 5, 22, GRAY, scale=1)
g.append(status_label)

# Scrollable results area (y=36 to y=220, ~12 lines at scale 1)
result_lines = []
for i in range(14):
    line = L("", 5, 36 + i * 14, WHITE, scale=1)
    g.append(line)
    result_lines.append(line)

# Hints
hint1 = L("Turn: scroll   Push: mode", 10, 226, DIM_GRAY, scale=1)
g.append(hint1)
hint2 = L("KEY0: scan", 10, 236, DIM_GRAY, scale=1)
g.append(hint2)

# Scanning spinner
spinner = L("", 290, 22, CYAN, scale=1)
g.append(spinner)

display.root_group = g
print("TFT ready.")

# ══════════════════════════════════════════════════════════════════════
#  4. Scanner Functions
# ══════════════════════════════════════════════════════════════════════

SIGNAL_CHARS = "▁▂▃▄▅▆▇█"

def rssi_to_bar(rssi):
    """Convert RSSI (-100 to -30) to a signal bar string (0-8 chars)."""
    if rssi >= -30:   n = 8
    elif rssi >= -40: n = 7
    elif rssi >= -50: n = 6
    elif rssi >= -60: n = 5
    elif rssi >= -70: n = 4
    elif rssi >= -80: n = 3
    elif rssi >= -90: n = 2
    else:             n = 1
    return SIGNAL_CHARS[n-1] * n + "░" * (8 - n)

def do_wifi_scan():
    """Scan for Wi-Fi networks. Returns list of (ssid, rssi, auth)."""
    global scanning
    print("Scanning Wi-Fi...")
    scanning = True
    results = []
    try:
        scan_iter = wifi.radio.start_scanning_networks()
        import time as _t
        deadline = _t.monotonic() + 5
        while _t.monotonic() < deadline:
            try:
                net = scan_iter.__next__()
                ssid = net.ssid.strip() if net.ssid else "(hidden)"
                auth = AUTH_NAMES.get(net.authmode, f"C{net.authmode}")
                results.append((ssid, net.rssi, auth))
                if len(results) >= 20:
                    break
            except StopIteration:
                _t.sleep(0.2)
            except TypeError:
                continue
    except Exception as e:
        err = str(e)
        print(f"Wi-Fi err: {err}")
        if "hash" in err or "list" in err:
            return [("CP bug: scan API broken", -99, "")]
    finally:
        try:
            wifi.radio.stop_scanning_networks()
        except Exception:
            pass
    # Sort by RSSI (strongest first)
    results.sort(key=lambda r: -r[1])
    scanning = False
    print(f"Found {len(results)} networks")
    return results

def do_ble_scan():
    """Scan for BLE devices. Returns list of (name, rssi, address)."""
    global scanning
    if _bleio is None:
        return [("BLE not on this board", 0, "")]
    print("Scanning BLE...")
    scanning = True
    results = []
    seen = set()
    try:
        _bleio.adapter.start_scan(timeout=3)
        start = time.monotonic()
        while time.monotonic() - start < 4:
            for entry in _bleio.adapter.scan_results:
                dev_addr = str(entry.address)
                if dev_addr in seen:
                    continue
                seen.add(dev_addr)
                name = entry.name or "(unnamed)"
                results.append((name, entry.rssi, dev_addr))
                if len(results) >= 15:
                    break
            if len(results) >= 15:
                break
            time.sleep(0.1)
        _bleio.adapter.stop_scan()
    except Exception as e:
        print(f"BLE scan error: {e}")
        results.append((f"Error: {e}", 0, ""))
    finally:
        try:
            _bleio.adapter.stop_scan()
        except Exception:
            pass
    results.sort(key=lambda r: -r[1])
    scanning = False
    print(f"Found {len(results)} BLE devices")
    return results

def run_scan():
    """Run the current mode's scan and update display."""
    global scan_results, scroll_pos
    spinner.text = "*"
    if mode == "wifi":
        scan_results = do_wifi_scan()
    else:
        scan_results = do_ble_scan()
    scroll_pos = 0
    spinner.text = ""
    update_display()

def update_display():
    """Refresh all display elements."""
    global scroll_pos, scan_results

    # Title + mode
    if mode == "wifi":
        mode_label.text = "Wi-Fi"
        mode_label.color = GREEN
    else:
        mode_label.text = "BLE"
        mode_label.color = BLUE

    # Count
    n = len(scan_results)
    status_label.text = f"{n} device{'s' if n != 1 else ''} found"

    # Adjust scroll bounds
    max_pos = max(0, len(scan_results) - len(result_lines))
    if scroll_pos > max_pos:
        scroll_pos = max_pos
    if scroll_pos < 0:
        scroll_pos = 0

    # Render visible results
    for i, line in enumerate(result_lines):
        idx = scroll_pos + i
        if idx < len(scan_results):
            item = scan_results[idx]
            if mode == "wifi":
                ssid, rssi, auth = item
                ssid_display = ssid[:18] if len(ssid) > 18 else ssid
                bar = rssi_to_bar(rssi)
                # Color by signal strength
                if rssi >= -50:
                    c = GREEN
                elif rssi >= -70:
                    c = YELLOW
                else:
                    c = GRAY
                line.color = c
                line.text = f"{idx+1}. {ssid_display}"
                # Show signal on next conceptual line
                # We use compact format: "SSID                  ████░░ -45"
                if i < len(result_lines) - 1 and idx + 1 < len(scan_results):
                    # Two items per two lines
                    pass
                # Compact single-line with bar
                bar_str = bar[:6]
                line.text = f"{idx+1:<2} {ssid_display:<16} {bar_str} {rssi:>3}"
            else:  # BLE
                name, rssi, addr = item
                name_disp = name[:18] if len(name) > 18 else name
                bar = rssi_to_bar(rssi)[:4]
                if rssi >= -50:
                    c = GREEN
                elif rssi >= -70:
                    c = YELLOW
                else:
                    c = GRAY
                line.color = c
                if addr:
                    # Short address for display
                    short_addr = addr[-5:] if len(addr) > 5 else addr
                    line.text = f"{idx+1:<2} {name_disp:<14} {bar} {short_addr}"
                else:
                    line.text = f"{idx+1:<2} {name_disp}"
        else:
            line.text = ""
            line.color = GRAY

# ══════════════════════════════════════════════════════════════════════
#  5. Main Loop
# ══════════════════════════════════════════════════════════════════════

print("Starting. Push to toggle mode, KEY0 to scan.")

# Initial display
update_display()

last_scan_time = 0
SCAN_COOLDOWN = 5  # seconds between auto-scans

while True:
    now = time.monotonic()
    ev = read_enc()

    if ev == 1:  # CW — scroll down
        scroll_pos += 1
        if scroll_pos > max(0, len(scan_results) - len(result_lines)):
            scroll_pos = max(0, len(scan_results) - len(result_lines))
        update_display()

    elif ev == -1:  # CCW — scroll up
        scroll_pos -= 1
        if scroll_pos < 0:
            scroll_pos = 0
        update_display()

    elif ev == 99:  # Push — toggle mode + scan
        mode = "ble" if mode == "wifi" else "wifi"
        scan_results = []
        scroll_pos = 0
        print(f"Mode: {mode.upper()}")
        update_display()
        # Auto-scan after switching mode
        run_scan()

    elif ev == 98:  # KEY0 — force rescan
        if not scanning:
            run_scan()

    # Auto-initial scan if no results
    if len(scan_results) == 0 and not scanning and (now - last_scan_time) > SCAN_COOLDOWN:
        run_scan()
        last_scan_time = now

    time.sleep(0.01)
