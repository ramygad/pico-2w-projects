# Pico 2W — Mini Video Player (fast)
# ================================================================
# Plays short procedural animations on the ST7789 TFT.
# Uses efficient buffer fills for smooth playback.
#
# Controls:
#   Turn encoder: switch animation
#   Push: play/pause
#   KEY0: reset
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
import random
import math
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

W, H = 320, 240

# ── Colours (RGB565) ───────────────────────────────────────────────────
def rgb(r,g,b): return ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
BLACK=rgb(0,0,0); WHITE=rgb(255,255,255); CYAN=rgb(0,255,255)
YELLOW=rgb(255,255,0); GREEN=rgb(0,255,0); RED=rgb(255,0,0)
BLUE=rgb(0,0,255); GRAY=rgb(100,100,100); DG=rgb(60,60,60)

# ══════════════════════════════════════════════════════════════════════
#  Init TFT
# ══════════════════════════════════════════════════════════════════════
print("Init TFT...")
displayio.release_displays()
spi = busio.SPI(TFT_SCK, TFT_MOSI)
dbus = FourWire(spi, command=TFT_DC, chip_select=TFT_CS, reset=TFT_RES)
disp = ST7789(dbus, width=W, height=H, rotation=270)

# ══════════════════════════════════════════════════════════════════════
#  Init Encoder
# ══════════════════════════════════════════════════════════════════════
print("Init encoder...")
ea=digitalio.DigitalInOut(ENC_A);ea.direction=digitalio.Direction.INPUT;ea.pull=digitalio.Pull.UP
eb=digitalio.DigitalInOut(ENC_B);eb.direction=digitalio.Direction.INPUT;eb.pull=digitalio.Pull.UP
ep=digitalio.DigitalInOut(ENC_PUSH);ep.direction=digitalio.Direction.INPUT;ep.pull=digitalio.Pull.UP
k0=digitalio.DigitalInOut(KEY0);k0.direction=digitalio.Direction.INPUT;k0.pull=digitalio.Pull.UP
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
#  Build UI
# ══════════════════════════════════════════════════════════════════════

g=displayio.Group()
g.append(label.Label(terminalio.FONT,text="VIDEO PLAYER",color=CYAN,x=5,y=4))
tl=label.Label(terminalio.FONT,text="",color=YELLOW,x=5,y=20); g.append(tl)
fl=label.Label(terminalio.FONT,text="",color=DG,x=260,y=20); g.append(fl)
pl=label.Label(terminalio.FONT,text="",color=GREEN,x=230,y=20); g.append(pl)

# Video bitmap
bmp=displayio.Bitmap(W,H,256)
pal=displayio.Palette(256)
for i in range(256): pal[i]=rgb(min(255,i*2),min(255,i),i//2) if i<200 else rgb(255,200-i+50,0)
g.append(displayio.TileGrid(bmp,pixel_shader=pal,x=0,y=36))
g.append(label.Label(terminalio.FONT,text="Turn: anim  Push: pause",color=DG,x=5,y=230))
g.append(label.Label(terminalio.FONT,text="KEY0: reset",color=DG,x=5,y=238))
disp.root_group=g
print("TFT ready.")

# ══════════════════════════════════════════════════════════════════════
#  Fast drawing helpers
# ══════════════════════════════════════════════════════════════════════

def fill(c):
    """Fast full-screen fill."""
    for x in range(W):
        for y in range(H):
            bmp[x,y]=c

def hline(y,x1,x2,c):
    """Fast horizontal line."""
    if y<0 or y>=H: return
    x1=max(0,x1); x2=min(W-1,x2)
    for x in range(x1,x2+1): bmp[x,y]=c

def vline(x,y1,y2,c):
    """Fast vertical line."""
    if x<0 or x>=W: return
    y1=max(0,y1); y2=min(H-1,y2)
    for y in range(y1,y2+1): bmp[x,y]=c

def rect(x,y,w,h,c):
    """Fill rectangle."""
    for ix in range(max(0,x),min(W,x+w)):
        for iy in range(max(0,y),min(H,y+h)):
            bmp[ix,iy]=c

def circle(cx,cy,r,c):
    """Filled circle using scanline fill."""
    for y in range(max(0,cy-r),min(H,cy+r+1)):
        dy=y-cy
        dx=int((r*r-dy*dy)**0.5) if r*r>=dy*dy else 0
        for x in range(max(0,cx-dx),min(W,cx+dx+1)):
            bmp[x,y]=c

# ══════════════════════════════════════════════════════════════════════
#  Animations (generators yielding after each frame)
# ══════════════════════════════════════════════════════════════════════

NAMES=["Bouncing Ball","Waves","Rainbow Bars","Maze","Fire"]

# 1. Bouncing ball with trail
def anim_ball():
    bx,by=W//2,H//2; bvx,bvy=3,2
    px,py=0,0; r=8
    f=0
    while True:
        # Erase old ball position (small rect)
        rect(px-r,py-r,r*2+1,r*2+1,0)
        # Draw ball
        circle(bx,by,r,200+(f%55))
        px,py=bx,by
        bx+=bvx;by+=bvy
        if bx<=r or bx>=W-r: bvx=-bvx
        if by<=r or by>=H-r: bvy=-bvy
        bx=max(r,min(W-r,bx))
        by=max(r,min(H-r,by))
        yield; f+=1

# 2. Sine waves (fast hline)
def anim_waves():
    t=0
    while True:
        fill(0)
        for y in range(H):
            s1=int(W//2+math.sin((y+t)*0.1)*40)
            s2=int(W//2+math.sin((y*2+t)*0.08)*20)
            hline(y,max(0,s1-10),min(W,s1+10),50+(y%200))
            hline(y,max(0,s2-5),min(W,s2+5),200-(y%150))
        yield; t+=1

# 3. Rainbow bars (hline fills)
def anim_bars():
    t=0
    while True:
        t+=1
        for y in range(0,H,4):
            c=(y+t*2)%256
            hline(y,0,W-1,c)
            if y+1<H: hline(y+1,0,W-1,c)
        yield

# 4. Color spiral (rectangular version)
def anim_maze():
    t=0
    while True:
        t+=1
        fill(0)
        for i in range(20):
            r=i*12+int(math.sin(t*0.1+i*0.3)*8)
            x=W//2-r; y=H//2-r; s=r*2
            color=(i*12+t*5)%256
            rect(x,y,s,2,color)
            rect(x,y,2,s,color)
            rect(x,y+s,s,2,color)
            rect(x+s,y,2,s,color)
        yield

# 5. Fire effect (hline-based)
def anim_fire():
    buf=[0]*W
    t=0
    while True:
        t+=1
        # Scroll up
        for y in range(H-1,0,-1):
            for x in range(W):
                c=bmp[x,y-1]
                bmp[x,y]=max(0,c-1)
        # New row at bottom
        for x in range(W):
            v=random.randint(0,255)
            bmp[x,H-1]=v
        yield

ANIMS=[anim_ball,anim_waves,anim_bars,anim_maze,anim_fire]

# ══════════════════════════════════════════════════════════════════════
#  Main Loop
# ══════════════════════════════════════════════════════════════════════

idx=0; play=True; gen=None; fc=0; lft=time.monotonic(); ffc=0; fps=0

def start(i):
    global idx,gen,fc
    idx=i%len(ANIMS)
    tl.text=NAMES[idx]
    fc=0; gen=ANIMS[idx]()
    fill(0)

print("Starting...")
start(0)

while True:
    ev=rd()
    if ev==1 and not play:
        start((idx+1)%len(ANIMS)); play=True; pl.text=""
    elif ev==-1 and not play:
        start((idx-1)%len(ANIMS)); play=True; pl.text=""
    elif ev==99:
        play=not play; pl.text="" if play else "PAUSED"
        if play: start(idx)
    elif ev==98:
        start(idx); play=True; pl.text=""
    
    if play and gen:
        try: next(gen); fc+=1
        except StopIteration: gen=ANIMS[idx]()
        
        ffc+=1
        n=time.monotonic()
        if n-lft>=2:
            fps=ffc/(n-lft)
            fl.text=f"{int(fps)}fps"
            print(f"{NAMES[idx]}: {int(fps)}fps")
            ffc=0; lft=n
    
    time.sleep(0.005)
