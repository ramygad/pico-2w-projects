#!/bin/bash
# Deploy weather_tft.py as code.py to the Pico 2W
# The Pico must be running CircuitPython and mounted as D:
#
# Usage:  bash deploy_weather_tft.sh
#
# First-time setup requires these files in the project:
#   lib/adafruit_display_text/  (extracted from Adafruit bundle)
#   adafruit_st7789.py          (in project root)
#   wifi_config.py              (in project root, gitignored)

PROJECT=/c/Users/engra/pic2w_projects

echo "=== Deploy Weather TFT to Pico 2W ==="
echo ""

# 1. Deploy the main program as code.py
echo "  [1/4]  weather_tft.py  ->  D:/code.py"
cp "$PROJECT/weather_tft.py" /d/code.py

# 2. adafruit_st7789 driver (once)
if [ ! -f /d/lib/adafruit_st7789.py ]; then
    echo "  [2/4]  adafruit_st7789.py  ->  D:/lib/"
    cp "$PROJECT/adafruit_st7789.py" /d/lib/
else
    echo "  [2/4]  adafruit_st7789.py          already on Pico"
fi

# 3. adafruit_display_text library (once)
if [ ! -d /d/lib/adafruit_display_text ]; then
    echo "  [3/4]  lib/adafruit_display_text/  ->  D:/lib/"
    cp -r "$PROJECT/lib/adafruit_display_text/" /d/lib/adafruit_display_text/
else
    echo "  [3/4]  adafruit_display_text/      already on Pico"
fi

# 4. Wi-Fi credentials (once)
if [ ! -f /d/wifi_config.py ]; then
    echo "  [4/4]  wifi_config.py  ->  D:/"
    cp "$PROJECT/wifi_config.py" /d/
else
    echo "  [4/4]  wifi_config.py              already on Pico"
fi

echo ""
echo "=== Done! Press Ctrl+D on REPL or reset the Pico to run. ==="
