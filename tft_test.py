# Test: single bar at different position — same pixel count as working test

import time
import board
import digitalio
import busio

cs = digitalio.DigitalInOut(board.GP4); cs.direction = digitalio.Direction.OUTPUT; cs.value = True
dc = digitalio.DigitalInOut(board.GP5); dc.direction = digitalio.Direction.OUTPUT
rst = digitalio.DigitalInOut(board.GP6); rst.direction = digitalio.Direction.OUTPUT
spi = busio.SPI(clock=board.GP2, MOSI=board.GP3)

def ms(t): time.sleep(t/1000)
def tx(buf):
    while not spi.try_lock(): pass
    spi.configure(baudrate=50000000, polarity=0, phase=0, bits=8)
    cs.value = False; spi.write(bytearray(buf)); cs.value = True
    spi.unlock()
def cmd(b): dc.value = False; tx([b])
def data(buf): dc.value = True; tx(buf)

rst.value = False; ms(10); rst.value = True; ms(10)
cmd(0x01); ms(150); cmd(0x11); ms(200)
cmd(0x36); data([0xE0]); ms(10)
cmd(0x3A); data([0x55]); ms(10)
cmd(0x21); ms(10); cmd(0x13); ms(10); cmd(0x29); ms(100)

# Draw same pixel count (9600) as working bar, but at a different position
# CASET: cols 80-119 (40px wide) — same 40px width as working
# RASET: rows 0-239 — same full height as working
# Same bytearray size as working test
cmd(0x2A); data([0x00, 0x50, 0x00, 0x77])  # cols 80-119
cmd(0x2B); data([0x00, 0x00, 0x00, 0xEF])  # rows 0-239
cmd(0x2C)
dc.value = True
while not spi.try_lock(): pass
cs.value = False
px = bytearray([0xF8, 0x00]) * (40 * 240)  # EXACT same as working test
spi.write(px)
cs.value = True
spi.unlock()
print("Bar at col 80: RED expected")

# Draw another bar at col 140
cmd(0x2A); data([0x00, 0x8C, 0x00, 0xB3])  # cols 140-179
cmd(0x2B); data([0x00, 0x00, 0x00, 0xEF])  # rows 0-239
cmd(0x2C)
dc.value = True
while not spi.try_lock(): pass
cs.value = False
# DIFFERENT pixel count: 40px * 240 = 9600 — same as working
px = bytearray([0x00, 0x1F]) * (40 * 240)
spi.write(px)
cs.value = True
spi.unlock()
print("Bar at col 140: BLUE expected")

while True: time.sleep(1)
