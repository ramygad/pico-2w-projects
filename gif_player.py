# Pico 2W — GIF Video Player
# ================================================================
# Plays animated GIF files on the ST7789 TFT.
#
# Put a .gif file on the CIRCUITPY drive, then run this program.
# The GIF will be scaled to fit the 320x240 screen.
#
# Controls:
#   Turn encoder: switch GIF files (if multiple)
#   Push: play/pause
#   KEY0: restart
#
# Pinout:
#   TFT: SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6
#   EC11: A=GP7, B=GP8, Push=GP9
#   KEY0: GP13
# ================================================================

import time
import board
import busio
import displayio
import terminalio
import digitalio
import os
from fourwire import FourWire
from adafruit_st7789 import ST7789
from adafruit_display_text import label

# ── Pins ────────────────────────────────────────────────────────────────
TFT_SCK=board.GP2; TFT_MOSI=board.GP3; TFT_CS=board.GP4
TFT_DC=board.GP5; TFT_RES=board.GP6
ENC_A=board.GP7; ENC_B=board.GP8; ENC_PUSH=board.GP9; KEY0_KEY=board.GP13
W,H=320,240

# ── Colours ────────────────────────────────────────────────────────────
CYAN=0x00FFFF; YELLOW=0xFFDD00; GREEN=0x00FF00; DG=0x555555

# ══════════════════════════════════════════════════════════════════════
#  Init TFT
# ══════════════════════════════════════════════════════════════════════
print("Init TFT...")
displayio.release_displays()
spi=busio.SPI(TFT_SCK,TFT_MOSI)
dbus=FourWire(spi,command=TFT_DC,chip_select=TFT_CS,reset=TFT_RES)
disp=ST7789(dbus,width=W,height=H,rotation=270)

# ══════════════════════════════════════════════════════════════════════
#  Init Encoder
# ══════════════════════════════════════════════════════════════════════
print("Init encoder...")
ea=digitalio.DigitalInOut(ENC_A);ea.direction=digitalio.Direction.INPUT;ea.pull=digitalio.Pull.UP
eb=digitalio.DigitalInOut(ENC_B);eb.direction=digitalio.Direction.INPUT;eb.pull=digitalio.Pull.UP
ep=digitalio.DigitalInOut(ENC_PUSH);ep.direction=digitalio.Direction.INPUT;ep.pull=digitalio.Pull.UP
k0=digitalio.DigitalInOut(KEY0_KEY);k0.direction=digitalio.Direction.INPUT;k0.pull=digitalio.Pull.UP

TT={(0,1):1,(0,2):-1,(1,0):-1,(1,3):1,(2,0):1,(2,3):-1,(3,1):-1,(3,2):1}
es=(ea.value<<1)|eb.value;els=es;ec=0;epv=ep.value;k0v=k0.value;lrt=0;lpt=0;lkt=0

def rd():
    global els,ec,epv,k0v,lrt,lpt,lkt
    n=time.monotonic();a=ea.value;b=eb.value;cs=(a<<1)|b
    if cs!=els:
        d=TT.get((els,cs),0);els=cs
        if d:
            ec+=d
            if abs(ec)>=4:
                ec=0
                if (n-lrt)>0.012:lrt=n;return d
    pv=ep.value
    if pv!=epv:
        epv=pv
        if not pv and (n-lpt)>0.3:lpt=n;return 99
    kv=k0.value
    if kv!=k0v:
        k0v=kv
        if not kv and (n-lkt)>0.3:lkt=n;return 98
    return 0

# ══════════════════════════════════════════════════════════════════════
#  Find GIF files
# ══════════════════════════════════════════════════════════════════════
gif_files = [f for f in os.listdir('/') if f.lower().endswith('.gif')]
print(f"Found {len(gif_files)} GIFs: {gif_files}")

if not gif_files:
    print("No GIF files found!")
    # Show message on TFT
    g=displayio.Group()
    g.append(label.Label(terminalio.FONT,text="No GIF files found!",color=0xFF0000,x=30,y=100))
    g.append(label.Label(terminalio.FONT,text="Copy a .gif to CIRCUITPY drive",color=0x888888,x=20,y=120))
    disp.root_group=g
    while True: time.sleep(1)

# ══════════════════════════════════════════════════════════════════════
#  Display a GIF
# ══════════════════════════════════════════════════════════════════════
import gifio

current_gif = 0
gif = None
tilegrid = None
playing = True

def load_gif(idx):
    global gif, tilegrid, g
    name = gif_files[idx]
    print(f"Loading: {name}")
    
    # Remove old tilegrid if exists
    if tilegrid and tilegrid in g:
        try:
            g.remove(tilegrid)
        except: pass
    
    # Open GIF
    try:
        gif = gifio.OnDiskGif(open(f"/{name}", "rb"))
    except Exception as e:
        print(f"Open failed: {e}")
        return
    
    # Create tilegrid (truecolor GIF -> use ColorConverter)
    tilegrid = displayio.TileGrid(gif.bitmap, pixel_shader=displayio.ColorConverter())
    
    # Center on screen (GIF may be smaller than display)
    gif_w = gif.bitmap.width
    gif_h = gif.bitmap.height
    tx = max(0, (W - gif_w) // 2)
    ty = max(36, (H - gif_h) // 2)  # leave room for title
    tilegrid.x = tx
    tilegrid.y = ty
    
    # Build UI
    g = displayio.Group()
    g.append(label.Label(terminalio.FONT,text="GIF PLAYER",color=CYAN,x=5,y=4))
    gt = label.Label(terminalio.FONT,text=f"{name} ({gif_w}x{gif_h})",color=YELLOW,x=5,y=20)
    g.append(gt)
    g.append(tilegrid)
    g.append(label.Label(terminalio.FONT,text="Push: pause  KEY0: restart",color=DG,x=5,y=230))
    g.append(label.Label(terminalio.FONT,text="Turn: next GIF",color=DG,x=5,y=238))
    
    disp.root_group = g
    
    # Play through once to buffer
    try:
        for _ in range(3):
            gif.next_frame()
    except: pass
    print(f"Loaded {name}")

# Load first GIF
load_gif(0)

# ══════════════════════════════════════════════════════════════════════
#  Main Loop
# ══════════════════════════════════════════════════════════════════════
print("Playing...")

while True:
    ev = rd()
    
    if ev == 1:  # Next GIF
        current_gif = (current_gif + 1) % len(gif_files)
        load_gif(current_gif)
        playing = True
    elif ev == -1:  # Previous GIF
        current_gif = (current_gif - 1) % len(gif_files)
        load_gif(current_gif)
        playing = True
    elif ev == 99:  # Toggle play/pause
        playing = not playing
    elif ev == 98:  # Restart
        load_gif(current_gif)
        playing = True
    
    if playing and gif:
        try:
            if not gif.next_frame():
                # GIF ended, restart
                load_gif(current_gif)
        except Exception as e:
            print(f"Frame error: {e}")
            time.sleep(0.1)
    
    time.sleep(0.001)
