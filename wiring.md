# Pico 2W — 2.4" ST7789 TFT + EC11 Encoder + Key0 Wiring

## Pin assignments

| Device | Module Pin | Pico 2W GPIO | Notes |
|--------|-----------|-------------|-------|
| **TFT** | VCC | 3.3V | |
| | GND | GND | |
| | SCL (SCK) | **GP2** | SPI0 SCK |
| | SDA (MOSI) | **GP3** | SPI0 TX |
| | CS | **GP4** | Chip select |
| | DC | **GP5** | Data/Command |
| | RES | **GP6** | Reset |
| | BLK | NC (or 3.3V) | Enabled by default on module |
| **EC11** | A | **GP7** | Quadrature phase A |
| **Encoder** | B | **GP8** | Quadrature phase B |
| | Push | **GP9** | Encoder push button |
| **Button** | KEY0 | **GP13** | 2nd push button |

⚠️ All encoder/button inputs use internal pull-up. Connect the other side of each switch to **GND**.

## Shared bus note

GP10/11/12 are reserved for **I2S audio** (PCM5102 / MAX98357A). This TFT + encoder setup avoids those pins — no conflict.

## Quick test

Flash `tft_test.py` as `code.py` on the Pico:

```
cmd.exe /c "copy C:\Users\engra\pic2w_projects\tft_test.py D:\code.py"
```

Also deploy the ST7789 driver (once):

```
cmd.exe /c "copy C:\Users\engra\pic2w_projects\adafruit_st7789.py D:\lib\"
```

Then open serial monitor at 115200 baud to see encoder/button events.

## Dependencies

- `adafruit_st7789.py` → `lib/` on CIRCUITPY drive
- `displayio`, `busio`, `digitalio` — built into CircuitPython 10.2.1
- `adafruit_display_text` — optional, for prettier text
