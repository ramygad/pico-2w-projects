# Pico 2W — Melody Player
# ================================================================
# Plays famous melodies through I2S DACs.
# UI via ST7789 TFT + EC11 encoder.
#
# Features:
#   - 10 famous melodies in playlist
#   - I2S audio via GY-PCM5102 (sine wave synthesis)
#   - Song title, artist, progress bar on TFT
#   - Turn encoder: scroll songs
#   - Push encoder: play/pause
#   - KEY0: skip to next song
#   - Non-blocking playback with encoder polling
#
# Pinout:
#   TFT:   SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6
#   I2S:   BCK=GP10, LCK=GP11, DIN=GP12
#   EC11:  A=GP7, B=GP8, Push=GP9
#   KEY0:  GP13
# ================================================================

import time
import board
import busio
import displayio
import terminalio
import digitalio
import array
import math
import audiobusio
import audiocore
from fourwire import FourWire
from adafruit_st7789 import ST7789
from adafruit_display_text import label

# ── Pin Assignments ────────────────────────────────────────────────────
TFT_SCK  = board.GP2
TFT_MOSI = board.GP3
TFT_CS   = board.GP4
TFT_DC   = board.GP5
TFT_RES  = board.GP6

I2S_BCK  = board.GP10
I2S_LCK  = board.GP11
I2S_DIN  = board.GP12

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
GRAY     = 0x888888
DIM_GRAY = 0x444444
RED      = 0xFF4444
BLUE     = 0x4488FF
PURPLE   = 0xAA44FF

# ── Audio ───────────────────────────────────────────────────────────────
SAMPLE_RATE = 22050
TONE_VOLUME = 14000  # 0-32767

# MIDI note frequencies (A4 = 440Hz = MIDI 69)
def midi_to_freq(n):
    return 440.0 * (2.0 ** ((n - 69) / 12.0))

# Generate sine wave sample for a given frequency and duration
def make_sine(freq_hz, duration_s):
    nsamples = int(SAMPLE_RATE * duration_s)
    if nsamples == 0:
        nsamples = 1
    buf = array.array("h", [0]) * nsamples
    step = 2.0 * math.pi * freq_hz / SAMPLE_RATE
    for i in range(nsamples):
        buf[i] = int(math.sin(step * i) * TONE_VOLUME)
    return audiocore.RawSample(buf, sample_rate=SAMPLE_RATE)

# Generate silence
def make_silence(duration_s):
    nsamples = int(SAMPLE_RATE * duration_s)
    if nsamples == 0:
        nsamples = 1
    buf = array.array("h", [0]) * nsamples
    return audiocore.RawSample(buf, sample_rate=SAMPLE_RATE)

# ── Melody data ─────────────────────────────────────────────────────────
# Format: (name, artist, [(midi_note, beats), ...])
# note=0 = rest. Tempo = BPM. Beat = quarter note.

TEMPO = 120
BEAT_DURATION = 60.0 / TEMPO

def b(beats):
    """Convert beats to seconds."""
    return beats * BEAT_DURATION

PLAYLIST = [
    ("Happy Birthday", "Traditional", [
        (67,0.5),(67,0.5),(69,1),(67,1),(72,1),(71,2),
        (67,0.5),(67,0.5),(69,1),(67,1),(74,1),(72,2),
        (67,0.5),(67,0.5),(79,1),(76,1),(72,1),(71,0.5),(69,0.5),
        (77,0.5),(77,0.5),(76,1),(72,1),(74,1),(72,2),
    ]),
    ("Twinkle Twinkle", "Traditional", [
        (60,1),(60,1),(67,1),(67,1),(69,1),(69,1),(67,2),
        (65,1),(65,1),(64,1),(64,1),(62,1),(62,1),(60,2),
        (67,1),(67,1),(65,1),(65,1),(64,1),(64,1),(62,2),
        (67,1),(67,1),(65,1),(65,1),(64,1),(64,1),(62,2),
        (60,1),(60,1),(67,1),(67,1),(69,1),(69,1),(67,2),
        (65,1),(65,1),(64,1),(64,1),(62,1),(62,1),(60,2),
    ]),
    ("Ode to Joy", "Beethoven", [
        (64,0.75),(64,0.75),(65,0.75),(67,0.75),(67,0.75),(65,0.75),(64,0.75),(62,0.75),
        (60,0.75),(60,0.75),(62,0.75),(64,0.75),(64,1.5),(62,0.75),(0,0.75),
        (64,0.75),(64,0.75),(65,0.75),(67,0.75),(67,0.75),(65,0.75),(64,0.75),(62,0.75),
        (60,0.75),(60,0.75),(62,0.75),(64,0.75),(62,1.5),(60,0.75),(0,0.75),
    ]),
    ("Jingle Bells", "J. Pierpont", [
        (64,0.5),(64,0.5),(64,1),(64,0.5),(64,0.5),(64,1),
        (64,0.5),(67,0.5),(60,0.5),(62,0.5),(64,2),
        (65,0.5),(65,0.5),(65,0.5),(65,0.5),(65,0.5),(64,0.5),(64,0.5),(64,0.5),
        (64,0.5),(62,0.5),(62,0.5),(64,0.5),(62,1),(67,1),
        (64,0.5),(64,0.5),(64,1),(64,0.5),(64,0.5),(64,1),
        (64,0.5),(67,0.5),(60,0.5),(62,0.5),(64,2),
        (65,0.5),(65,0.5),(65,0.5),(65,0.5),(65,0.5),(64,0.5),(64,0.5),(64,0.5),
        (67,0.5),(67,0.5),(65,0.5),(62,0.5),(60,2),
    ]),
    ("Imperial March", "J. Williams", [
        (67,1),(67,1),(67,2),(64,1.5),(70,0.5),(67,2),(64,1.5),(70,0.5),(67,4),
        (75,1),(75,1),(75,2),(72,1.5),(78,0.5),(75,2),(72,1.5),(78,0.5),(75,4),
    ]),
    ("Mario Theme", "Kondo", [
        (76,0.25),(76,0.25),(0,0.25),(76,0.25),
        (0,0.25),(72,0.25),(76,0.25),(0,0.25),
        (79,0.5),(0,0.25),(67,0.25),(0,0.25),
        (76,0.25),(0,0.25),(72,0.25),(0,0.25),(79,0.25),
        (0,0.25),
    ]),
    ("Fuer Elise", "Beethoven", [
        (76,0.5),(75,0.5),(76,0.5),(75,0.5),(76,0.5),(71,0.5),(74,0.5),(72,0.5),(69,1),
        (76,0.5),(75,0.5),(76,0.5),(75,0.5),(76,0.5),(71,0.5),(74,0.5),(72,0.5),(69,1),
        (72,0.5),(71,0.5),(72,0.5),(71,0.5),(72,0.5),(67,0.5),(69,0.5),(71,0.5),(60,1),
    ]),
    ("Amazing Grace", "Traditional", [
        (67,1),(60,1),(64,1.5),(62,0.5),(60,2),
        (67,1),(60,1),(64,1.5),(62,0.5),(60,2),
        (64,1),(62,1),(60,1),(64,1),(67,2),
        (64,1),(62,1),(60,1),(64,1.5),(60,0.5),(67,2),
    ]),
    ("Take On Me", "A-ha", [
        (80,0.5),(83,0.5),(86,0.5),(89,0.5),(0,0.5),
        (86,0.5),(84,0.5),(81,0.5),(78,0.5),(0,0.5),
        (80,0.5),(83,0.5),(86,0.5),(89,0.5),(0,0.5),
        (86,0.5),(84,0.5),(81,0.5),(78,0.5),(0,0.5),
        (74,0.5),(76,0.5),(78,0.5),(80,0.5),(83,1.5),(0,0.5),
    ]),
    ("Over the Rainbow", "H. Arlen", [
        (72,0.5),(67,0.5),(65,0.5),(67,1.5),(64,0.5),
        (60,0.5),(62,0.5),(64,0.5),(65,1.5),(60,0.5),
        (64,0.5),(65,0.5),(67,0.5),(69,0.5),(72,0.5),(76,0.5),
        (72,0.5),(69,0.5),(67,1.5),(0,0.5),
        (72,0.5),(67,0.5),(65,0.5),(67,1.5),(64,0.5),
        (60,0.5),(62,0.5),(64,0.5),(65,1.5),(60,0.5),
        (64,0.5),(65,0.5),(67,0.5),(64,0.5),(62,2),
    ]),
]

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
ROT_DB = 0.015
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
#  3. Init I2S Audio
# ══════════════════════════════════════════════════════════════════════
print("Init I2S...")
audio = audiobusio.I2SOut(bit_clock=I2S_BCK, word_select=I2S_LCK, data=I2S_DIN)
print("I2S ready.")

# ══════════════════════════════════════════════════════════════════════
#  4. Build UI Layout
# ══════════════════════════════════════════════════════════════════════

def L(text, x, y, color=WHITE, scale=1):
    return label.Label(terminalio.FONT, text=text, color=color, x=x, y=y, scale=scale)

g = displayio.Group()

# Title
g.append(L("MELODY PLAYER", 5, 4, CYAN, scale=2))

# Status
status_label = L("", 5, 22, GRAY, scale=1)
g.append(status_label)

# Play/Pause icon
playing_icon = L("", 290, 4, GREEN, scale=2)
g.append(playing_icon)

# Divider line (just use a label)
g.append(L("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", 5, 36, DIM_GRAY, scale=1))

# Song selector elements
g.append(L("Playlist:", 5, 40, DIM_GRAY, scale=1))

# Song list (scrollable)
MAX_SONG_LINES = 9
song_lines = []
for i in range(MAX_SONG_LINES):
    line = L("", 10, 56 + i * 14, WHITE, scale=1)
    g.append(line)
    song_lines.append(line)

# Now playing (bottom)
now_label = L("Now playing:", 5, 188, DIM_GRAY, scale=1)
g.append(now_label)
song_title = L("", 5, 202, YELLOW, scale=1)
g.append(song_title)
artist_label = L("", 5, 214, GRAY, scale=1)
g.append(artist_label)

# Progress bar
PROG_X = 120
PROG_Y = 202
PROG_W = 195
PROG_H = 5
prog_bitmap = displayio.Bitmap(PROG_W, PROG_H, 2)
prog_palette = displayio.Palette(2)
prog_palette[0] = 0x222222
prog_palette[1] = GREEN
prog_sprite = displayio.TileGrid(prog_bitmap, pixel_shader=prog_palette, x=PROG_X, y=PROG_Y)
g.append(prog_sprite)

# Hints
g.append(L("Turn: select  Push: play/pause", 10, 230, DIM_GRAY, scale=1))
g.append(L("KEY0: skip", 10, 240, DIM_GRAY, scale=1))

display.root_group = g
print("TFT ready.")

# ══════════════════════════════════════════════════════════════════════
#  5. Melody Player Engine
# ══════════════════════════════════════════════════════════════════════

def draw_progress(fraction):
    filled = int(PROG_W * fraction)
    if filled > PROG_W: filled = PROG_W
    for x in range(PROG_W):
        for y in range(PROG_H):
            prog_bitmap[x, y] = 1 if x < filled else 0

def update_song_list(selected_idx):
    """Update the visible song list on screen."""
    n = len(PLAYLIST)
    for i, line in enumerate(song_lines):
        idx = i
        if idx < n:
            name = PLAYLIST[idx][0]
            if idx == selected_idx:
                line.color = CYAN
                line.text = f" ▸ {name}"
            else:
                line.color = WHITE
                line.text = f"   {idx+1}. {name}"
        else:
            line.text = ""
            line.color = WHITE

def play_song(song_idx):
    """Play a song. Returns True if completed, False if interrupted (user input)."""
    global playing
    if song_idx >= len(PLAYLIST):
        return False
    
    name, artist, notes = PLAYLIST[song_idx]
    total_notes = len(notes)
    
    # Update now-playing display
    song_title.text = f"{name[:20]}"
    artist_label.text = f"{artist[:20]}"
    playing_icon.text = "▶"
    status_label.text = "Playing"
    
    # Pre-cache silence (used between notes)
    silence = make_silence(0.04)
    
    for ni, (midi_note, beats) in enumerate(notes):
        # Check for user input during playback
        ev = read_enc()
        if ev == 99:  # Push = pause/stop
            playing = False
            return False
        if ev == 98:  # KEY0 = skip
            playing = False
            return False  # caller will advance to next song
        
        # Update progress
        progress = ni / total_notes
        draw_progress(progress)
        
        # Play note or rest
        if midi_note > 20:  # valid note
            duration_s = beats * BEAT_DURATION
            # Shorten slightly for articulation
            play_s = duration_s * 0.9
            tone = make_sine(midi_to_freq(midi_note), play_s)
            audio.play(tone)
            time.sleep(play_s)
            audio.stop()
        time.sleep(0.04)  # slight gap between notes
    
    draw_progress(1)
    return True  # completed

# ══════════════════════════════════════════════════════════════════════
#  6. Main Loop
# ══════════════════════════════════════════════════════════════════════

current_song = 0
playing = False

print("Starting. Turn to select, push to play.")
status_label.text = "Ready"
playing_icon.text = "⏹"
update_song_list(0)

last_skip_t = 0

while True:
    ev = read_enc()
    now = time.monotonic()

    if not playing:
        if ev == 1:  # CW — next song
            current_song = (current_song + 1) % len(PLAYLIST)
            update_song_list(current_song)
            song_title.text = ""
            artist_label.text = ""
            draw_progress(0)
            status_label.text = "Ready"

        elif ev == -1:  # CCW — prev song
            current_song = (current_song - 1) % len(PLAYLIST)
            update_song_list(current_song)
            song_title.text = ""
            artist_label.text = ""
            draw_progress(0)
            status_label.text = "Ready"

        elif ev == 99:  # Push — play
            playing = True
            print(f"Playing: {PLAYLIST[current_song][0]}")
            completed = play_song(current_song)
            if completed:
                # Auto-advance to next song
                current_song = (current_song + 1) % len(PLAYLIST)
                update_song_list(current_song)
                playing_icon.text = "⏹"
                status_label.text = "Done"
                draw_progress(0)
            else:
                # Stopped by user
                playing_icon.text = "⏸"
                status_label.text = "Paused"
            playing = False

        elif ev == 98:  # KEY0 — skip (when not playing, just select next)
            if (now - last_skip_t) > 0.5:
                current_song = (current_song + 1) % len(PLAYLIST)
                update_song_list(current_song)
                last_skip_t = now
    else:
        # Playing — the play_song function handles input internally
        # If we get here, playback ended
        pass

    time.sleep(0.01)
