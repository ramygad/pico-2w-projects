# Pico 2W — I2S Function Generator
# ================================================================
# Generates sine/square/triangle/sawtooth waveforms via I2S DACs.
# UI via ST7789 TFT + EC11 encoder.
#
# Features:
#   - 4 waveform types: sine, square, triangle, sawtooth
#   - Adjustable frequency: 1 Hz – 20 kHz
#   - Adjustable amplitude: 0.00 – 1.00
#   - Waveform visualization on TFT
#   - I2S output to both GY-PCM5102 + MAX98357A simultaneously
#
# Pinout:
#   TFT:   SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6
#   EC11:  A=GP7, B=GP8, Push=GP9
#   KEY0:  GP13  (waveform type toggle)
#   I2S:   BCK=GP10, LCK=GP11, DIN=GP12
# ================================================================

import time
import math
import board
import busio
import displayio
import terminalio
import digitalio
import audiobusio
import audiocore
import array
from fourwire import FourWire
from adafruit_st7789 import ST7789
from adafruit_display_text import label

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

# ── Audio parameters ────────────────────────────────────────────────────
SAMPLE_RATE = 44100
MAX_BUF     = 4096  # max samples for tone buffer (16KB for 16-bit mono)
FREQ_MIN    = 1
FREQ_MAX    = 20000
AMP_MIN     = 0.0
AMP_MAX     = 1.0
AMP_STEP    = 0.02

# ── Waveform types ───────────────────────────────────────────────────────
WAVEFORMS = ["Sine", "Square", "Triangle", "Sawtooth"]
N_WAVES = len(WAVEFORMS)

# ── Current state ────────────────────────────────────────────────────────
current_wave = 0       # 0=sine, 1=square, 2=triangle, 3=sawtooth
current_freq = 440.0   # Hz
current_amp  = 0.5     # 0.0 – 1.0
active_param = "freq"  # "freq" or "amp"

# ══════════════════════════════════════════════════════════════════════
#  1. Initialise I2S Audio
# ══════════════════════════════════════════════════════════════════════
print("Init I2S audio...")
audio_i2s = None
try:
    audio_i2s = audiobusio.I2SOut(board.GP10, board.GP11, board.GP12)
    print(f"I2S ready ({SAMPLE_RATE} Hz)")
except Exception as e:
    print(f"I2S init failed: {e}")

# ══════════════════════════════════════════════════════════════════════
#  2. Initialise EC11 Encoder + KEY0
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

# Quadrature state machine with transition table
# EC11 produces 4 state transitions per detent click.
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
key0_prev = key0.value

last_rot_time = 0
last_push_time = 0
last_key0_time = 0
ROT_DEBOUNCE = 0.15
PUSH_DEBOUNCE = 0.3

def read_encoder_and_keys():
    """Read encoder rotation, push, and KEY0.
    Returns: 0=nothing, 1=CW, -1=CCW, 99=push, 98=KEY0 press"""
    global enc_last_state, enc_counter, enc_push_prev, key0_prev
    global last_rot_time, last_push_time, last_key0_time

    now = time.monotonic()

    # ── Rotation (quadrature transition table) ──────────────────────
    a_val = enc_a.value
    b_val = enc_b.value
    cur_state = (a_val << 1) | b_val
    if cur_state != enc_last_state:
        key = (enc_last_state, cur_state)
        direction = TRANS_TABLE.get(key, 0)
        enc_last_state = cur_state
        if direction != 0:
            enc_counter += direction
            if abs(enc_counter) >= 4:
                enc_counter = 0
                if (now - last_rot_time) > ROT_DEBOUNCE:
                    last_rot_time = now
                    return direction  # 1=CW, -1=CCW

    # ── Push button ─────────────────────────────────────────────────
    push_val = enc_push.value
    if push_val != enc_push_prev:
        enc_push_prev = push_val
        if not push_val:  # pressed (low)
            if (now - last_push_time) > PUSH_DEBOUNCE:
                last_push_time = now
                return 99

    # ── KEY0 ────────────────────────────────────────────────────────
    k0 = key0.value
    if k0 != key0_prev:
        key0_prev = k0
        if not k0:  # pressed (low)
            if (now - last_key0_time) > PUSH_DEBOUNCE:
                last_key0_time = now
                return 98

    return 0

# ══════════════════════════════════════════════════════════════════════
#  3. Initialise TFT Display
# ══════════════════════════════════════════════════════════════════════
print("Init TFT...")
displayio.release_displays()
spi = busio.SPI(clock=TFT_SCK, MOSI=TFT_MOSI)
display_bus = FourWire(spi, command=TFT_DC, chip_select=TFT_CS, reset=TFT_RES)
display = ST7789(display_bus, width=WIDTH, height=HEIGHT, rotation=270)

# ══════════════════════════════════════════════════════════════════════
#  4. Build UI Layout
# ══════════════════════════════════════════════════════════════════════

def make_label(text, x, y, color=WHITE, scale=1):
    return label.Label(terminalio.FONT, text=text, color=color, x=x, y=y, scale=scale)

main_group = displayio.Group()

# ── Title ───────────────────────────────────────────────────────────────
title = make_label("FUNCTION GENERATOR", 15, 4, CYAN, scale=2)
main_group.append(title)

# ── Waveform name ───────────────────────────────────────────────────────
wave_label = make_label("Sine", 5, 24, GREEN, scale=1)
main_group.append(wave_label)

# ── Waveform visualization bitmap ───────────────────────────────────────
WAVE_W = 300
WAVE_H = 56
WAVE_X = 10
WAVE_Y = 36

# Bitmap with 2 colors: 0=bg, 1=waveform color
wave_bitmap = displayio.Bitmap(WAVE_W, WAVE_H, 2)
wave_palette = displayio.Palette(2)
wave_palette[0] = 0x000000   # transparent black (shows display BG)
wave_palette[1] = YELLOW     # waveform line color
wave_sprite = displayio.TileGrid(wave_bitmap, pixel_shader=wave_palette, x=WAVE_X, y=WAVE_Y)
main_group.append(wave_sprite)

# ── Frequency display ───────────────────────────────────────────────────
freq_label = make_label("Freq: 440.0 Hz", 10, 94, YELLOW, scale=3)
main_group.append(freq_label)

# ── Amplitude display ───────────────────────────────────────────────────
amp_label = make_label("Amp: 0.50", 10, 122, GRAY, scale=3)
main_group.append(amp_label)

# ── Sample rate / bits info ─────────────────────────────────────────────
info1 = make_label(f"Sample: {SAMPLE_RATE} Hz  16-bit", 5, 150, DIM_GRAY, scale=1)
main_group.append(info1)

# ── Controls hint ───────────────────────────────────────────────────────
hint1 = make_label("Turn: adjust    Push: toggle", 10, 170, GRAY, scale=1)
main_group.append(hint1)
hint2 = make_label("KEY0: wave type", 10, 182, GRAY, scale=1)
main_group.append(hint2)

# ── Active param indicator ──────────────────────────────────────────────
active_indicator = make_label(">", 0, 94, YELLOW, scale=3)  # placed beside active param
main_group.append(active_indicator)

display.root_group = main_group
print("TFT ready.")

# ══════════════════════════════════════════════════════════════════════
#  5. Waveform Generation
# ══════════════════════════════════════════════════════════════════════

def generate_waveform(freq, amp, wavetype):
    """Generate a RawSample for the given frequency, amplitude, and wave type.
    Returns a buffer with integer number of cycles; loops cleanly."""
    if amp <= 0:
        return None

    samples_per_cycle = SAMPLE_RATE / freq
    if samples_per_cycle < 1:
        freq = SAMPLE_RATE  # clamp to Nyquist-ish
        samples_per_cycle = 1.0

    # Compute integer number of cycles that fits in MAX_BUF
    cycles = max(1, int(MAX_BUF / samples_per_cycle))
    n = int(samples_per_cycle * cycles)
    n = min(n, MAX_BUF)

    buf = array.array('h', [0]) * n
    max_val = int(32767 * amp)

    if wavetype == 0:  # Sine
        for i in range(n):
            val = int(max_val * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
            buf[i] = val

    elif wavetype == 1:  # Square
        half_cycle = max(1, int(samples_per_cycle / 2))
        for i in range(n):
            buf[i] = max_val if (i % int(samples_per_cycle)) < half_cycle else -max_val

    elif wavetype == 2:  # Triangle
        half = samples_per_cycle / 2.0
        for i in range(n):
            phase = (i % int(samples_per_cycle)) / half  # 0..2
            if phase < 1.0:
                buf[i] = int(max_val * (2 * phase - 1))
            else:
                buf[i] = int(max_val * (1 - 2 * (phase - 1)))

    elif wavetype == 3:  # Sawtooth
        for i in range(n):
            phase = (i % int(samples_per_cycle)) / samples_per_cycle
            buf[i] = int(max_val * (2 * phase - 1))

    return audiocore.RawSample(buf, sample_rate=SAMPLE_RATE)

def draw_waveform():
    """Draw the current waveform into wave_bitmap."""
    wave_bitmap.fill(0)  # clear
    for x in range(WAVE_W):
        phase = 2.0 * math.pi * x / WAVE_W * 3  # 3 cycles across the display
        mid = WAVE_H // 2
        amp_px = mid - 3  # leave 3px padding top/bottom
        y = mid

        if current_wave == 0:  # Sine
            y = mid - int(amp_px * math.sin(phase))
        elif current_wave == 1:  # Square
            y = mid - amp_px if (x % (WAVE_W // 3)) < (WAVE_W // 6) else mid + amp_px
        elif current_wave == 2:  # Triangle
            sub_phase = (x % (WAVE_W // 3)) / (WAVE_W // 3)  # 0..1
            if sub_phase < 0.5:
                y = mid - int(amp_px * (1 - 4 * sub_phase))
            else:
                y = mid - int(amp_px * (4 * sub_phase - 3))
        elif current_wave == 3:  # Sawtooth
            sub_phase = (x % (WAVE_W // 3)) / (WAVE_W // 3)
            y = mid + int(amp_px * (1 - 2 * sub_phase))

        y = max(0, min(WAVE_H - 1, y))
        wave_bitmap[x, y] = 1
        # Draw 2px thick line
        if y > 0:
            wave_bitmap[x, y - 1] = 1
        if y < WAVE_H - 1:
            wave_bitmap[x, y + 1] = 1

# ══════════════════════════════════════════════════════════════════════
#  6. UI Update Functions
# ══════════════════════════════════════════════════════════════════════

def update_display():
    """Refresh all UI elements to match current state."""
    # Waveform name
    wave_label.text = WAVEFORMS[current_wave]

    # Frequency
    if current_amp <= 0:
        freq_label.text = "Freq: ---"
    else:
        freq_label.text = f"Freq: {current_freq:.1f} Hz"

    # Amplitude
    amp_label.text = f"Amp:  {current_amp:.2f}"

    # Active indicator position
    if active_param == "freq":
        active_indicator.text = ">"
        active_indicator.y = 94
        freq_label.color = YELLOW
        amp_label.color = GRAY
    else:
        active_indicator.text = ">"
        active_indicator.y = 122
        freq_label.color = GRAY
        amp_label.color = YELLOW

    # Waveform visualization
    draw_waveform()

def apply_audio():
    """Generate and play the current waveform through the DACs."""
    global audio_i2s
    if audio_i2s is None or current_amp <= 0:
        if audio_i2s is not None:
            try:
                audio_i2s.stop()
            except:
                pass
        return

    try:
        # Stop current playback
        audio_i2s.stop()
    except:
        pass

    try:
        tone = generate_waveform(current_freq, current_amp, current_wave)
        if tone is not None:
            audio_i2s.play(tone, loop=True)
    except Exception as e:
        print(f"Audio gen error: {e}")

# ══════════════════════════════════════════════════════════════════════
#  7. Parameter Adjustment Logic
# ══════════════════════════════════════════════════════════════════════

def adjust_freq(delta):
    """Adjust frequency by delta steps. Delta is +1 (CW) or -1 (CCW)."""
    global current_freq
    if abs(delta) < 1:
        return

    step = delta
    # Dynamic step size based on current frequency range
    if current_freq < 10:
        step *= 0.5
    elif current_freq < 100:
        step *= 1.0
    elif current_freq < 500:
        step *= 10.0
    elif current_freq < 2000:
        step *= 50.0
    else:
        step *= 100.0

    current_freq = round(current_freq + step, 1)
    current_freq = max(FREQ_MIN, min(FREQ_MAX, current_freq))

def adjust_amp(delta):
    """Adjust amplitude by delta steps."""
    global current_amp
    current_amp = round(current_amp + AMP_STEP * delta, 2)
    current_amp = max(AMP_MIN, min(AMP_MAX, current_amp))

# ══════════════════════════════════════════════════════════════════════
#  8. Main Loop
# ══════════════════════════════════════════════════════════════════════

print("Starting main loop. Turn encoder to adjust, push to toggle param, KEY0 for wave.")

# Initial render + audio
draw_waveform()
update_display()
apply_audio()

need_audio_update = False
need_display_update = False

while True:
    event = read_encoder_and_keys()

    if event == 1:  # CW — increase active param
        if active_param == "freq":
            adjust_freq(1)
        else:
            adjust_amp(1)
        need_display_update = True
        need_audio_update = True

    elif event == -1:  # CCW — decrease active param
        if active_param == "freq":
            adjust_freq(-1)
        else:
            adjust_amp(-1)
        need_display_update = True
        need_audio_update = True

    elif event == 99:  # Push — toggle active parameter
        active_param = "amp" if active_param == "freq" else "freq"
        need_display_update = True
        print(f"Active: {active_param}")

    elif event == 98:  # KEY0 — cycle waveform type
        current_wave = (current_wave + 1) % N_WAVES
        need_display_update = True
        need_audio_update = True
        print(f"Wave: {WAVEFORMS[current_wave]}")

    if need_display_update:
        update_display()
        need_display_update = False

    if need_audio_update:
        apply_audio()
        need_audio_update = False

    time.sleep(0.01)