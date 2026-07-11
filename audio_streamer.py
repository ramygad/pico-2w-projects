# Pico 2W — Wi-Fi Audio Streamer
# ================================================================
# Receives audio over UDP Wi-Fi and plays through I2S DACs.
# Serves a web control page for iPhone/browser.
#
# Features:
#   - UDP audio streaming (44100 Hz, 16-bit, mono)
#   - Web UI: http://<pico-ip>/ — upload/play WAV files
#   - TFT display: song name, volume, playback state
#   - EC11 encoder: turn volume, push play/pause
#   - KEY0: skip/next track
#   - Output to both GY-PCM5102 + MAX98357A simultaneously
#
# Pinout:
#   TFT:   SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6
#   EC11:  A=GP7, B=GP8, Push=GP9
#   KEY0:  GP13
#   I2S:   BCK=GP10, LCK=GP11, DIN=GP12
# ================================================================

import time
import math
import struct
import board
import busio
import displayio
import terminalio
import digitalio
import wifi
import socketpool
import audiobusio
import audiocore
import array
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

I2S_BCK  = board.GP10
I2S_LCK  = board.GP11
I2S_DIN  = board.GP12

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
BLUE     = 0x4488FF

# ── Audio parameters ────────────────────────────────────────────────────
SAMPLE_RATE = 44100
AUDIO_VOL   = 0.30
BUF_SAMPLES = 2048   # samples per audio buffer (~46ms @ 44100)
BUF_BYTES   = BUF_SAMPLES * 2  # 16-bit = 2 bytes/sample
VOL_MIN     = 0.0
VOL_MAX     = 1.0
VOL_STEP    = 0.02

# ── State ────────────────────────────────────────────────────────────────
volume       = 0.3
playing      = False
paused       = False
connected    = False
song_name    = "---"
device_name  = "---"
client_ip    = None

# ══════════════════════════════════════════════════════════════════════
#  1. Init TFT Display
# ══════════════════════════════════════════════════════════════════════
print("Init TFT...")
displayio.release_displays()
spi = busio.SPI(clock=TFT_SCK, MOSI=TFT_MOSI)
display_bus = FourWire(spi, command=TFT_DC, chip_select=TFT_CS, reset=TFT_RES)
display = ST7789(display_bus, width=WIDTH, height=HEIGHT, rotation=270)

# ══════════════════════════════════════════════════════════════════════
#  2. Init I2S Audio
# ══════════════════════════════════════════════════════════════════════
print("Init I2S audio...")
audio_i2s = None
try:
    audio_i2s = audiobusio.I2SOut(I2S_BCK, I2S_LCK, I2S_DIN)
    print(f"I2S ready ({SAMPLE_RATE} Hz)")
except Exception as e:
    print(f"I2S failed: {e}")

# ══════════════════════════════════════════════════════════════════════
#  3. Init Encoder + KEY0
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
    # Rotation
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
                    return d  # 1=CW, -1=CCW
    # Push
    pv = enc_push.value
    if pv != enc_push_prev:
        enc_push_prev = pv
        if not pv and (now - last_push_t) > PUSH_DEBOUNCE:
            last_push_t = now
            return 99
    # KEY0
    k0 = key0.value
    if k0 != key0_prev:
        key0_prev = k0
        if not k0 and (now - last_key0_t) > PUSH_DEBOUNCE:
            last_key0_t = now
            return 98
    return 0

# ══════════════════════════════════════════════════════════════════════
#  4. Build UI Layout
# ══════════════════════════════════════════════════════════════════════

def L(text, x, y, color=WHITE, scale=1):
    return label.Label(terminalio.FONT, text=text, color=color, x=x, y=y, scale=scale)

g = displayio.Group()

# Title
g.append(L("AUDIO STREAMER", 40, 4, CYAN, scale=2))

# Connected device
g.append(L("Device:", 5, 26, DIM_GRAY, scale=1))
dev_label = L(device_name, 80, 26, WHITE, scale=1)
g.append(dev_label)

# Song name
g.append(L("Now Playing:", 5, 44, DIM_GRAY, scale=1))
song_label = L(song_name, 10, 60, YELLOW, scale=2)
g.append(song_label)

# Volume
vol_label = L(f"Vol: {int(volume*100)}%", 10, 90, CYAN, scale=3)
g.append(vol_label)

# Volume bar
VOL_BAR_W = 300
VOL_BAR_H = 8
VOL_BAR_X = 10
VOL_BAR_Y = 118
vol_bar_bitmap = displayio.Bitmap(VOL_BAR_W, VOL_BAR_H, 2)
vol_bar_palette = displayio.Palette(2)
vol_bar_palette[0] = 0x222222   # dim background
vol_bar_palette[1] = CYAN       # level color
vol_bar_sprite = displayio.TileGrid(vol_bar_bitmap, pixel_shader=vol_bar_palette, x=VOL_BAR_X, y=VOL_BAR_Y)
g.append(vol_bar_sprite)

# Playback state
state_label = L("---", 10, 135, GREEN, scale=2)
g.append(state_label)

# Connection info
ip_label = L("IP: connecting...", 5, 162, GRAY, scale=1)
g.append(ip_label)

# Controls hint
g.append(L("Turn: volume  Push: play/pause", 10, 182, DIM_GRAY, scale=1))
g.append(L("KEY0: skip", 10, 194, DIM_GRAY, scale=1))

# Spinning indicator
spin_chars = ["|", "/", "-", "\\"]
spin_idx = 0
spin_label = L("", 290, 0, GRAY, scale=1)
g.append(spin_label)

display.root_group = g
print("TFT ready.")

def draw_vol_bar():
    """Draw the volume level bar."""
    filled = int(VOL_BAR_W * volume)
    for x in range(VOL_BAR_W):
        for y in range(VOL_BAR_H):
            col = 1 if x < filled else 0
            vol_bar_bitmap[x, y] = col

def update_display():
    song_label.text = song_name if len(song_name) <= 20 else song_name[:17] + "..."
    dev_label.text = device_name
    vol_label.text = f"Vol: {int(volume * 100)}%"
    draw_vol_bar()

    if not connected and not playing:
        state_label.text = "Waiting..."
        state_label.color = GRAY
    elif paused:
        state_label.text = "Paused"
        state_label.color = ORANGE
    elif playing:
        state_label.text = "Playing"
        state_label.color = GREEN
    else:
        state_label.text = "Idle"
        state_label.color = GRAY

# ══════════════════════════════════════════════════════════════════════
#  5. Wi-Fi + UDP Server
# ══════════════════════════════════════════════════════════════════════

print("Connecting to Wi-Fi...")
ip_label.text = "Wi-Fi..."
for attempt in range(5):
    try:
        wifi.radio.connect(wifi_config.SSID, wifi_config.PASSWORD)
        ip = str(wifi.radio.ipv4_address)
        print(f"OK: {ip}")
        ip_label.text = f"IP: {ip}  (port 8888)"
        break
    except Exception as e:
        print(f"Wi-Fi attempt {attempt+1}: {e}")
        time.sleep(2)
else:
    print("Wi-Fi failed")
    ip_label.text = "Wi-Fi FAIL"

pool = socketpool.SocketPool(wifi.radio)

# UDP socket for audio
udp_sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
udp_sock.bind(("0.0.0.0", 8888))
udp_sock.settimeout(0)  # non-blocking
print("UDP listening on port 8888")

# TCP socket for HTTP control
tcp_sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
tcp_sock.bind(("0.0.0.0", 80))
tcp_sock.listen(1)
tcp_sock.settimeout(0)
print("HTTP ready on port 80")

# ══════════════════════════════════════════════════════════════════════
#  6. Audio Ring Buffer
# ══════════════════════════════════════════════════════════════════════

# Double buffer for audio playback
AUDIO_RING_SIZE = 8  # number of buffers in ring
audio_ring = [array.array('h', [0]) * BUF_SAMPLES for _ in range(AUDIO_RING_SIZE)]
write_idx = 0
read_idx = 0
ring_count = 0
current_sample = None

# Volume scaling lookup table (pre-computed for speed)
VOL_TABLE = [int(32767 * v) for v in [i / 100.0 for i in range(101)]]

def scale_audio(raw_buf, vol_idx):
    """Scale a raw buffer array by volume index (0-100)."""
    max_v = VOL_TABLE[vol_idx]
    for i in range(len(raw_buf)):
        raw_buf[i] = (raw_buf[i] * max_v) >> 15

def start_playback():
    """Start playing from the read buffer."""
    global current_sample, playing, paused
    if ring_count == 0:
        return
    src = audio_ring[read_idx]
    scaled = array.array('h', src)  # copy
    scale_audio(scaled, int(volume * 100))
    current_sample = audiocore.RawSample(scaled, sample_rate=SAMPLE_RATE)
    if audio_i2s:
        audio_i2s.play(current_sample, loop=True)
    playing = True
    paused = False

def stop_playback():
    """Stop audio output."""
    global playing, current_sample
    if audio_i2s:
        try:
            audio_i2s.stop()
        except:
            pass
    playing = False
    current_sample = None

# ══════════════════════════════════════════════════════════════════════
#  7. HTTP Web UI Handler
# ══════════════════════════════════════════════════════════════════════

HTML_PAGE = """HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
Connection: close

<!DOCTYPE html>
<html>
<head>
 <meta charset="utf-8">
 <meta name="viewport" content="width=device-width,initial-scale=1">
 <title>Pico Streamer</title>
 <style>
  body{font-family:sans-serif;background:#111;color:#ddd;padding:20px;max-width:600px;margin:auto}
  h1{color:#0ff}
  .card{background:#222;border-radius:8px;padding:16px;margin:16px 0}
  .card h2{margin:0 0 8px 0;font-size:16px;color:#888}
  .val{font-size:28px;color:#0ff}
  .btn{display:inline-block;padding:12px 24px;margin:4px;border:none;border-radius:6px;font-size:16px;cursor:pointer}
  .btn:active{opacity:0.7}
  .green{background:#0a0;color:#fff}
  .red{background:#a00;color:#fff}
  .blue{background:#00a;color:#fff}
  input{width:100%;padding:8px;margin:4px 0;background:#333;border:1px solid #555;color:#ddd;border-radius:4px;box-sizing:border-box}
  .status{font-size:14px;color:#0f0}
 </style>
</head>
<body>
 <h1>Pico 2W Streamer</h1>
 <div class="card">
  <h2>Song</h2>
  <div class="val" id="song">--</div>
 </div>
 <div class="card">
  <h2>Device</h2>
  <div id="dev" class="val">--</div>
 </div>
 <div class="card">
  <h2>Volume</h2>
  <div id="vol" class="val">30%</div>
  <input type="range" min="0" max="100" value="30" id="volSlider" oninput="setVol(this.value)">
 </div>
 <div class="card">
  <button class="btn green" onclick="fetch('/play')">Play</button>
  <button class="btn red" onclick="fetch('/pause')">Pause</button>
  <button class="btn blue" onclick="fetch('/next')">Next</button>
 </div>
 <div class="card">
  <h2>Stream URL</h2>
  <input type="text" id="urlInput" placeholder="http://...">
  <button class="btn green" onclick="fetch('/stream?url='+encodeURIComponent(urlInput.value))">Stream</button>
 </div>
 <div id="status" class="status"></div>
 <script>
  function setVol(v){fetch('/volume?level='+v)}
  function doAction(a){fetch('/'+a)}
  setInterval(async()=>{
   const r=await fetch('/status');
   const d=await r.json();
   document.getElementById('song').textContent=d.song;
   document.getElementById('dev').textContent=d.device;
   document.getElementById('vol').textContent=d.volume+'%';
   document.getElementById('volSlider').value=d.volume;
   document.getElementById('status').textContent=d.state;
  },2000);
 </script>
</body>
</html>
""".replace("\n", "\r\n")

def handle_http():
    """Check for HTTP connections and handle requests."""
    try:
        conn, addr = tcp_sock.accept()
        conn.settimeout(2)
        data = conn.recv(4096)
        if data:
            req = data.decode('utf-8', errors='replace')
            path = req.split(" ")[1] if " " in req else "/"
            body = b""
            ct = "text/plain"

            if path == "/":
                body = HTML_PAGE.encode('utf-8')
                ct = "text/html"
            elif path == "/play":
                global paused
                paused = False
                body = b'{"ok":true}'
            elif path == "/pause":
                paused = True
                body = b'{"ok":true}'
            elif path == "/next" or path == "/skip":
                body = b'{"ok":true}'
            elif path.startswith("/volume?level="):
                try:
                    v = int(path.split("=")[1])
                    global volume
                    volume = max(0, min(100, v)) / 100.0
                except:
                    pass
                body = b'{"ok":true}'
            elif path == "/status":
                body = ('{"song":"%s","device":"%s","volume":%d,"state":"%s"}'
                       % (song_name, device_name, int(volume*100),
                          "paused" if paused else "playing" if playing else "idle")).encode()
                ct = "application/json"
            else:
                body = b'{"error":"not found"}'

            resp = ("HTTP/1.1 200 OK\r\n"
                    "Content-Type: %s\r\n"
                    "Content-Length: %d\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "\r\n" % (ct, len(body)))
            conn.send(resp.encode() + body)
        conn.close()
    except (BlockingIOError, OSError):
        pass
    except Exception as e:
        print(f"HTTP err: {e}")

# ══════════════════════════════════════════════════════════════════════
#  8. UDP Audio Receive
# ══════════════════════════════════════════════════════════════════════

def read_udp_audio():
    """Try to read a UDP audio packet. Returns bytes or None."""
    global client_ip, connected, device_name
    try:
        data, addr = udp_sock.recvfrom(BUF_BYTES + 256)
        if not connected:
            client_ip = addr[0]
            connected = True
            device_name = client_ip
            print(f"Client connected: {client_ip}")
    except (BlockingIOError, OSError):
        return None
    except Exception as e:
        return None

    # Parse packet
    # Format: [4-byte type][4-byte seq][audio data or metadata]
    if len(data) >= 8:
        pkt_type = struct.unpack_from(">I", data, 0)[0]
        seq = struct.unpack_from(">I", data, 4)[0]

        if pkt_type == 0:  # Audio data
            audio_data = data[8:]
            if len(audio_data) >= 4:  # at least 2 samples
                # Convert bytes to 16-bit signed array
                n = len(audio_data) // 2
                if n > BUF_SAMPLES:
                    n = BUF_SAMPLES
                samples = array.array('h', audio_data[:n*2])
                # Pad if needed
                while len(samples) < BUF_SAMPLES:
                    samples.append(0)
                return samples

        elif pkt_type == 1:  # Metadata
            meta = data[8:].decode('utf-8', errors='replace')
            parts = meta.split("||")
            if len(parts) >= 2:
                global song_name
                song_name = parts[0]
                device_name = parts[1]
                print(f"Meta: {song_name}  from {device_name}")

    return None

# ══════════════════════════════════════════════════════════════════════
#  9. Main Loop
# ══════════════════════════════════════════════════════════════════════

print("Main loop running.")
update_display()
last_display_t = time.monotonic()
audio_buf = None
need_audio_restart = False

while True:
    now = time.monotonic()

    # 1. Check UDP for audio data
    new_buf = read_udp_audio()
    if new_buf is not None:
        audio_buf = new_buf
        if not playing:
            need_audio_restart = True

    # 2. Handle audio playback
    if need_audio_restart and audio_i2s and audio_buf is not None and not paused:
        # Apply volume and play
        vol_idx = int(volume * 100)
        scaled = array.array('h', audio_buf)  # copy
        scale_audio(scaled, vol_idx)
        try:
            audio_i2s.stop()
        except:
            pass
        tone = audiocore.RawSample(scaled, sample_rate=SAMPLE_RATE)
        audio_i2s.play(tone, loop=True)
        playing = True
        need_audio_restart = False
        paused = False

    # 3. Handle pause/resume
    if paused and playing:
        try:
            audio_i2s.stop()
        except:
            pass
        playing = False

    # 4. Poll encoder
    ev = read_enc()
    if ev == 1:  # CW — volume up
        volume = min(VOL_MAX, volume + VOL_STEP)
        need_audio_restart = True
        print(f"Vol: {int(volume*100)}%")
    elif ev == -1:  # CCW — volume down
        volume = max(VOL_MIN, volume - VOL_STEP)
        need_audio_restart = True
        print(f"Vol: {int(volume*100)}%")
    elif ev == 99:  # Push — play/pause
        paused = not paused
        if not paused:
            need_audio_restart = True
        print(f"{'Pause' if paused else 'Play'}")
    elif ev == 98:  # KEY0 — skip/next
        audio_buf = None
        song_name = "---"
        device_name = client_ip or "---"
        try:
            audio_i2s.stop()
        except:
            pass
        playing = False
        print("Skip")

    # 5. Handle HTTP
    handle_http()

    # 6. Update display (throttled to ~10 Hz)
    if now - last_display_t > 0.1:
        spin_idx = (spin_idx + 1) % 4
        spin_label.text = spin_chars[spin_idx] if connected else ""
        update_display()
        last_display_t = now

    time.sleep(0.01)
