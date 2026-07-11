# Pico 2W — IP Network Scanner
# ================================================================
# Scans local network for active hosts and open ports.
# UI via ST7789 TFT + EC11 encoder.
#
# Features:
#   - Scans /24 subnet for active hosts
#   - Checks common ports: 22(SSH), 80(HTTP), 443(HTTPS), 8080
#   - Shows IP, hostname (if available), open ports
#   - Progress bar during scan
#   - Scroll through results via encoder
#   - Push to rescan, KEY0 for port detail toggle
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
import socketpool
import struct
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
KEY0     = board.GP13

WIDTH  = 320
HEIGHT = 240

# ── Colours ─────────────────────────────────────────────────────────────
WHITE    = 0xFFFFFF
CYAN     = 0x00FFFF
GREEN    = 0x00FF00
YELLOW   = 0xFFDD00
ORANGE   = 0xFF8800
GRAY     = 0x888888
DIM_GRAY = 0x444444
RED      = 0xFF4444

# ── Scan ports ──────────────────────────────────────────────────────────
SCAN_PORTS = [22, 80, 443, 8080]
PORT_NAMES = {22: "SSH", 80: "HTTP", 443: "HTTPS", 8080: "HTTP-alt"}
PORT_TIMEOUT = 0.1  # seconds per port check (100ms for LAN)

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

TRANS_TABLE = {
    (0, 1): 1,   (0, 2): -1, (1, 0): -1,  (1, 3): 1,
    (2, 0): 1,   (2, 3): -1, (3, 1): -1,  (3, 2): 1,
}
enc_s = (enc_a.value << 1) | enc_b.value
enc_last_s = enc_s
enc_cnt = 0
enc_push_prev = enc_push.value
key0_prev = key0.value
last_rot_t = 0
last_push_t = 0
last_key0_t = 0
ROT_DB = 0.01
PUSH_DB = 0.3

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
                if (now - last_rot_t) > ROT_DB:
                    last_rot_t = now
                    return d
    pv = enc_push.value
    if pv != enc_push_prev:
        enc_push_prev = pv
        if not pv and (now - last_push_t) > PUSH_DB:
            last_push_t = now
            return 99
    k0 = key0.value
    if k0 != key0_prev:
        key0_prev = k0
        if not k0 and (now - last_key0_t) > PUSH_DB:
            last_key0_t = now
            return 98
    return 0

# ══════════════════════════════════════════════════════════════════════
#  3. Build UI Layout
# ══════════════════════════════════════════════════════════════════════

def L(text, x, y, color=WHITE, scale=1):
    return label.Label(terminalio.FONT, text=text, color=color, x=x, y=y, scale=scale)

g = displayio.Group()

# Title
g.append(L("IP SCANNER", 5, 4, CYAN, scale=2))

# Our IP
ip_label = L("", 5, 22, DIM_GRAY, scale=1)
g.append(ip_label)

# Progress / status
status_label = L("", 5, 36, GRAY, scale=1)
g.append(status_label)

# Progress bar
PROG_BAR_X = 10
PROG_BAR_Y = 50
PROG_BAR_W = 300
PROG_BAR_H = 6
prog_bitmap = displayio.Bitmap(PROG_BAR_W, PROG_BAR_H, 2)
prog_palette = displayio.Palette(2)
prog_palette[0] = 0x222222
prog_palette[1] = CYAN
prog_sprite = displayio.TileGrid(prog_bitmap, pixel_shader=prog_palette, x=PROG_BAR_X, y=PROG_BAR_Y)
g.append(prog_sprite)

# Scrollable results (y=62 to y=218, ~11 lines)
MAX_RESULT_LINES = 11
result_lines = []
for i in range(MAX_RESULT_LINES):
    line = L("", 5, 62 + i * 14, WHITE, scale=1)
    g.append(line)
    result_lines.append(line)

# Hints
g.append(L("Turn: scroll  Push: rescan", 10, 228, DIM_GRAY, scale=1))
g.append(L("KEY0: port detail", 10, 238, DIM_GRAY, scale=1))

display.root_group = g
print("TFT ready.")

# ══════════════════════════════════════════════════════════════════════
#  4. Wi-Fi + Scanner
# ══════════════════════════════════════════════════════════════════════

def draw_progress(fraction):
    """Draw progress bar. fraction = 0.0 to 1.0"""
    filled = int(PROG_BAR_W * fraction)
    for x in range(PROG_BAR_W):
        for y in range(PROG_BAR_H):
            prog_bitmap[x, y] = 1 if x < filled else 0

def ip_to_str(ip_int):
    """Convert integer IP to string."""
    return f"{(ip_int>>24)&255}.{(ip_int>>16)&255}.{(ip_int>>8)&255}.{ip_int&255}"

def str_to_ip(s):
    """Convert string IP to integer."""
    parts = [int(x) for x in s.split('.')]
    return (parts[0]<<24) | (parts[1]<<16) | (parts[2]<<8) | parts[3]

def scan_network():
    """Scan the local subnet for active hosts and open ports.
    Returns list of (ip_str, [open_ports])."""
    global status_label
    
    my_ip = wifi.radio.ipv4_address
    ip_int = str_to_ip(str(my_ip))
    subnet_base = ip_int & 0xFFFFFF00  # /24 subnet
    my_last_octet = ip_int & 0xFF

    hosts = []
    scan_count = 254  # .1 to .254
    checked = 0

    pool = socketpool.SocketPool(wifi.radio)

    for last in range(1, 255):
        if last == my_last_octet:
            checked += 1
            continue  # skip our own IP

        target_ip = subnet_base | last
        ip_str = ip_to_str(target_ip)

        # Show progress
        status_label.text = f"Scanning {ip_str}..."
        progress = checked / scan_count
        if int(progress * 100) % 5 == 0:
            draw_progress(progress)

        open_ports = []

        # Check each common port
        for port in SCAN_PORTS:
            try:
                sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
                sock.settimeout(PORT_TIMEOUT)
                result = sock.connect_ex((ip_str, port))
                sock.close()
                if result == 0:
                    open_ports.append(port)
            except Exception:
                pass
        
        if open_ports:
            hosts.append((ip_str, open_ports))
            # Show on display immediately
            update_display()

        checked += 1

        # Update progress bar every 10 IPs
        if checked % 10 == 0:
            status_label.text = f"Scanning... {checked}/254  ({len(hosts)} found)"
            draw_progress(checked / 254)

    # Sort by IP
    hosts.sort(key=lambda h: str_to_ip(h[0]))
    return hosts

def run_scan():
    """Run the IP scan and update display."""
    global scan_results, scroll_pos
    scanning = True
    scroll_pos = 0
    status_label.text = "Scanning..."
    draw_progress(0)
    
    scan_results = scan_network()
    
    status_label.text = f"{len(scan_results)} hosts found"
    draw_progress(1)
    scanning = False
    update_display()

def update_display():
    """Refresh the display results."""
    global scroll_pos, scan_results
    n = len(scan_results)

    # Update IP display
    ip_label.text = f"My IP: {wifi.radio.ipv4_address}"

    # Adjust scroll
    max_pos = max(0, n - MAX_RESULT_LINES)
    if scroll_pos > max_pos: scroll_pos = max_pos
    if scroll_pos < 0: scroll_pos = 0

    # Render lines
    for i, line in enumerate(result_lines):
        idx = scroll_pos + i
        if idx < n:
            ip_str, ports = scan_results[idx]
            # Build port string
            port_strs = []
            for p in ports:
                name = PORT_NAMES.get(p, str(p))
                port_strs.append(name)
            ports_str = ",".join(port_strs) if port_strs else "?"
            
            # Format: "192.168.1.X  SSH,HTTP"
            # Color by number of ports
            if len(ports) >= 3:
                c = GREEN
            elif len(ports) >= 1:
                c = YELLOW
            else:
                c = GRAY

            line.color = c
            # Format nicely
            ip_short = ip_str  # full IP
            line.text = f"{idx+1:<2} {ip_short:<15} {ports_str}"
        else:
            line.text = ""
            line.color = GRAY

# ══════════════════════════════════════════════════════════════════════
#  5. Main Loop
# ══════════════════════════════════════════════════════════════════════

print("Connecting to Wi-Fi...")
status_label.text = "Wi-Fi..."
ip_label.text = "Connecting..."
wifi_ok = False
for attempt in range(5):
    try:
        wifi.radio.connect(wifi_config.SSID, wifi_config.PASSWORD)
        print(f"OK: {wifi.radio.ipv4_address}")
        ip_label.text = f"My IP: {wifi.radio.ipv4_address}"
        wifi_ok = True
        break
    except Exception as e:
        print(f"Wi-Fi try {attempt+1}: {e}")
        time.sleep(2)

if not wifi_ok:
    status_label.text = "Wi-Fi FAIL"
    print("Wi-Fi failed")

# Initial state
scan_results = []
scroll_pos = 0
update_display()

print("Starting. Push to scan, KEY0 for port detail.")
last_scan_time = 0

while True:
    ev = read_enc()

    if ev == 1:  # CW - scroll down
        scroll_pos += 1
        max_pos = max(0, len(scan_results) - MAX_RESULT_LINES)
        if scroll_pos > max_pos: scroll_pos = max_pos
        update_display()

    elif ev == -1:  # CCW - scroll up
        scroll_pos -= 1
        if scroll_pos < 0: scroll_pos = 0
        update_display()

    elif ev == 99:  # Push - run scan
        if len(scan_results) == 0 or (time.monotonic() - last_scan_time) > 2:
            run_scan()
            last_scan_time = time.monotonic()

    elif ev == 98:  # KEY0 - cycle port detail mode (placeholder)
        pass

    # Auto-scan on first run
    if len(scan_results) == 0 and wifi_ok and (time.monotonic() > 5):
        run_scan()
        last_scan_time = time.monotonic()

    time.sleep(0.01)
