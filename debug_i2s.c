/*
 * Step-by-step debug: test I2S PIO init and put_blocking
 */
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/gpio.h"
#include "hardware/clocks.h"
#include "i2s_audio.pio.h"

#define PIN_BCK    10
#define PIN_LCK    11
#define PIN_DIN    12
#define SAMPLE_RATE 48000
#define AMPLITUDE   12000

void blink_gp25(int times, int ms) {
    for (int i = 0; i < times; i++) {
        gpio_put(25, 1);
        sleep_ms(ms);
        gpio_put(25, 0);
        sleep_ms(ms);
    }
}

int main(void) {
    // LED on immediately — alive indicator
    gpio_init(25);
    gpio_set_dir(25, GPIO_OUT);
    gpio_put(25, 1);

    stdio_init_all();

    // Wait 5s for USB to enumerate
    blink_gp25(5, 250);  // 5 quick blinks = 2.5s
    blink_gp25(5, 500);  // 5 slow blinks = 5s

    printf("\n===== I2S PIO DEBUG =====\n");
    fflush(stdout);

    float sys_freq = (float)clock_get_hz(clk_sys);
    float divider  = sys_freq / (SAMPLE_RATE * 128.0f);
    printf("sys_freq=%.0f divider=%.3f\n", sys_freq, divider);
    fflush(stdout);

    // ── Setup I2S PIO ────────────────────────────────
    PIO  pio    = pio0;
    uint sm     = pio_claim_unused_sm(pio, true);
    uint offset = pio_add_program(pio, &i2s_audio_program);
    printf("pio0 sm=%d offset=%d\n", sm, offset);
    fflush(stdout);

    // GPIO init
    pio_gpio_init(pio, PIN_BCK);
    pio_gpio_init(pio, PIN_LCK);
    pio_gpio_init(pio, PIN_DIN);
    printf("gpio_init done\n");
    fflush(stdout);

    // SM config
    pio_sm_config c = i2s_audio_program_get_default_config(offset);
    sm_config_set_sideset_pins(&c, PIN_BCK);
    sm_config_set_out_pins(&c, PIN_DIN, 1);
    sm_config_set_out_shift(&c, true, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_clkdiv(&c, divider);
    printf("sm_config done\n");
    fflush(stdout);

    // Pin directions
    pio_sm_set_consecutive_pindirs(pio, sm, PIN_BCK, 2, true);
    pio_sm_set_consecutive_pindirs(pio, sm, PIN_DIN, 1, true);
    printf("pindirs done\n");
    fflush(stdout);

    // Init SM
    pio_sm_init(pio, sm, offset, &c);
    printf("sm_init done\n");
    fflush(stdout);

    // Enable SM
    pio_sm_set_enabled(pio, sm, true);
    printf("sm_enabled — trying put_blocking...\n");
    fflush(stdout);

    // Push one sample
    uint32_t test_word = (uint32_t)AMPLITUDE << 16;
    pio_sm_put_blocking(pio, sm, test_word);
    printf("first put_blocking OK\n");
    fflush(stdout);

    pio_sm_put_blocking(pio, sm, test_word);
    printf("second put_blocking OK\n");
    fflush(stdout);

    sleep_ms(100);
    printf("Still alive after 100ms\n");
    fflush(stdout);

    // ── Main loop ─────────────────────────────────────
    printf("\n===== Entering continuous loop =====\n");
    fflush(stdout);

    int64_t sample_counter = 0;
    int half_cycle = SAMPLE_RATE / 800 / 2;
    uint64_t last_blink = 0;

    while (true) {
        uint64_t now = to_ms_since_boot(get_absolute_time());
        if (now - last_blink > 1000) {
            gpio_put(25, !gpio_get(25));
            last_blink = now;
        }

        int pos = (int)(sample_counter % (uint64_t)(half_cycle * 2));
        int16_t raw = (pos < half_cycle) ? AMPLITUDE : -AMPLITUDE;
        uint32_t word = (uint32_t)(uint16_t)raw << 16;

        pio_sm_put_blocking(pio, sm, word);
        pio_sm_put_blocking(pio, sm, word);
        sample_counter++;
    }
    return 0;
}
