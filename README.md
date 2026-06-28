# Pico 2W Projects

Bare-metal C and CircuitPython firmware for the **Raspberry Pi Pico 2W** (RP2350).

## Projects

### LED S.O.S. Flasher (`sos_flasher.c`)

Blinks the onboard LED in Morse S.O.S. pattern. C firmware using `pico_cyw43_arch_none`.

### I2S Audio S.O.S. (`sos_audio.c` + `i2s_audio.pio`)

PIO-based I2S driver for GY-PCM5102 DAC — **not working** in C. Use the CircuitPython version instead.

### Wi-Fi Weather (`code.py` / `weather_tft.py`)

Fetches Open-Meteo weather for Mainz, Germany and displays on a **2.4" ST7789 TFT** (320x240).

Pinout: SCK=GP2, MOSI=GP3, CS=GP4, DC=GP5, RES=GP6

## Required Libraries

When deploying CircuitPython programs to the Pico, copy these to the `lib/` folder on the CIRCUITPY drive:

| Library | Source |
|---------|--------|
| `adafruit_st7789.mpy` | [Adafruit ST7789](https://github.com/adafruit/Adafruit_CircuitPython_ST7789) |
| `adafruit_display_text/` (folder) | [Adafruit Display Text](https://github.com/adafruit/Adafruit_CircuitPython_Display_Text) |
| `adafruit_requests.mpy` | [Adafruit Requests](https://github.com/adafruit/Adafruit_CircuitPython_Requests) |
| `adafruit_connection_manager.mpy` | [Adafruit Connection Manager](https://github.com/adafruit/Adafruit_CircuitPython_ConnectionManager) |

### Quick download

Grab the **Adafruit CircuitPython Library Bundle** for your CircuitPython version:

- **10.x (.mpy bundle):** https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases/download/20260627/adafruit-circuitpython-bundle-10.x-mpy-20260627.zip
- **All releases:** https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases

Extract the needed `.mpy` files from `lib/` inside the zip.

## Deploy

```bash
bash deploy_weather_tft.sh
```

## Build C firmware

```bash
export PICO_SDK_PATH=/c/Users/engra/pico-sdk
cmake -B build -G Ninja -DPICO_BOARD=pico2_w
ninja -C build <target>
```

Targets: `sos_flasher`, `sos_audio`, `test_alive`, `debug_pio`, `debug_i2s`, `debug_i2s2`, `debug_sos`.
