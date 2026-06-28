/*
 * Raspberry Pi Pico 2W — S.O.S. Flasher
 * =======================================
 * Blinks the onboard LED in S.O.S. Morse pattern and
 * prints diagnostics over USB serial.
 *
 * Uses pico_cyw43_arch_none (no WiFi stack, just LED control).
 *
 * Build:  cmake -B build -G Ninja && ninja -C build
 * Flash:  copy build/sos_flasher.uf2 to Pico in BOOTSEL mode
 */

#include <stdio.h>
#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "hardware/clocks.h"

// ── Constants ────────────────────────────────────────────────────────
#define UNIT_MS        150    // Morse dot duration (ms)
#define SHORT_GAP_MS   (UNIT_MS * 2)   // inter-letter gap
#define LONG_GAP_MS    (UNIT_MS * 4)   // inter-repeat gap

// ── LED helpers ──────────────────────────────────────────────────────
static inline void led_on(void)  { cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1); }
static inline void led_off(void) { cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 0); }

// ── Morse blinker ────────────────────────────────────────────────────
static void blink(int times, int ms) {
    for (int i = 0; i < times; i++) {
        led_on();
        sleep_ms(ms);
        led_off();
        sleep_ms(ms);
    }
}

static void flash_sos(void) {
    blink(3, UNIT_MS);              // S  ... (3 dots)
    sleep_ms(SHORT_GAP_MS);         // letter gap
    blink(3, UNIT_MS * 3);          // O  --- (3 dashes)
    sleep_ms(SHORT_GAP_MS);         // letter gap
    blink(3, UNIT_MS);              // S  ... (3 dots)
    sleep_ms(LONG_GAP_MS);          // repeat gap
}

// ── Status ───────────────────────────────────────────────────────────
static void print_status(void) {
    uint32_t freq_mhz  = clock_get_hz(clk_sys) / 1000000;
    uint64_t uptick_ms = to_ms_since_boot(get_absolute_time());

    printf(
        "\n"
        "────────────────────────────────────────────\n"
        "  Board:     Raspberry Pi Pico 2W\n"
        "  CPU Freq:  %u MHz\n"
        "  Uptick:    %llu s\n"
        "────────────────────────────────────────────\n"
        "  S.O.S. Flasher running — Ctrl+C to stop.\n",
        (unsigned)freq_mhz,
        (unsigned long long)(uptick_ms / 1000));
}

// ── Entry point ──────────────────────────────────────────────────────
int main(void) {
    stdio_init_all();

    // Allow USB serial to enumerate before we start printing
    sleep_ms(2000);

    printf("\n"
           "============================================\n"
           "  Pico 2W S.O.S. Flasher — Alive!\n"
           "============================================\n");

    // Initialise the CYW43 driver (needed for onboard LED)
    if (cyw43_arch_init()) {
        printf("ERROR: cyw43_arch_init failed\n");
        return 1;
    }

    printf("CYW43 ready.\n");

    // Blink loop
    uint64_t next_status = 0;
    while (true) {
        uint64_t now = time_us_64();
        if (now >= next_status) {
            print_status();
            next_status = now + 6000000;   // every ~6 s
        }
        flash_sos();
    }

    cyw43_arch_deinit();
    return 0;
}
