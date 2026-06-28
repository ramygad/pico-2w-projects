/*
 * Minimal I2S PIO test — print immediately, then init PIO step by step
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

void blink_led(void) {
    gpio_put(25, !gpio_get(25));
}

int main(void) {
    gpio_init(25);
    gpio_set_dir(25, GPIO_OUT);
    gpio_put(25, 1);

    stdio_init_all();

    // Print immediately — no delay
    printf("BOOT\n");
    fflush(stdout);
    sleep_ms(100);

    float sys_freq = (float)clock_get_hz(clk_sys);
    float divider  = sys_freq / (SAMPLE_RATE * 128.0f);
    printf("FREQ %.0f DIV %.3f\n", sys_freq, divider);
    fflush(stdout);
    sleep_ms(100);

    PIO  pio    = pio0;
    uint sm     = pio_claim_unused_sm(pio, true);
    uint offset = pio_add_program(pio, &i2s_audio_program);
    printf("PIO sm=%u offset=%u\n", sm, offset);
    fflush(stdout);
    blink_led();
    sleep_ms(100);

    pio_gpio_init(pio, PIN_BCK);
    pio_gpio_init(pio, PIN_LCK);
    pio_gpio_init(pio, PIN_DIN);
    printf("GPIO_INIT done\n");
    fflush(stdout);
    blink_led();
    sleep_ms(100);

    pio_sm_config c = i2s_audio_program_get_default_config(offset);
    sm_config_set_sideset_pins(&c, PIN_BCK);
    sm_config_set_out_pins(&c, PIN_DIN, 1);
    sm_config_set_out_shift(&c, true, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_clkdiv(&c, divider);
    printf("SM_CONFIG done\n");
    fflush(stdout);
    blink_led();
    sleep_ms(100);

    pio_sm_set_consecutive_pindirs(pio, sm, PIN_BCK, 2, true);
    pio_sm_set_consecutive_pindirs(pio, sm, PIN_DIN, 1, true);
    printf("PINDIRS done\n");
    fflush(stdout);
    blink_led();
    sleep_ms(100);

    pio_sm_init(pio, sm, offset, &c);
    printf("SM_INIT done\n");
    fflush(stdout);
    blink_led();
    sleep_ms(100);

    // ENABLE is the critical step
    printf("About to enable SM...\n");
    fflush(stdout);
    sleep_ms(100);

    pio_sm_set_enabled(pio, sm, true);
    printf("SM_ENABLED! Trying put_blocking...\n");
    fflush(stdout);
    blink_led();
    sleep_ms(100);

    uint32_t word = (uint32_t)12000 << 16;
    pio_sm_put_blocking(pio, sm, word);
    printf("PUT1 OK\n");
    fflush(stdout);
    blink_led();
    sleep_ms(100);

    pio_sm_put_blocking(pio, sm, word);
    printf("PUT2 OK\n");
    fflush(stdout);

    uint64_t last = 0;
    int count = 0;
    while (true) {
        uint64_t now = to_ms_since_boot(get_absolute_time());
        if (now - last > 1000) {
            blink_led();
            last = now;
            printf("tick %d\n", count++);
            fflush(stdout);
        }
        tight_loop_contents();
    }
    return 0;
}
