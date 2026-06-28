/*
 * Debug firmware — step by step to find the PIO init issue
 */
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/gpio.h"
#include "hardware/clocks.h"

#define PIN_BCK    10
#define PIN_LCK    11
#define PIN_DIN    12
#define SAMPLE_RATE 48000

void step(const char *msg) {
    printf("%s\n", msg);
    fflush(stdout);
    sleep_ms(250);
}

int main(void) {
    // Init LED
    gpio_init(25);
    gpio_set_dir(25, GPIO_OUT);
    gpio_put(25, 1);

    stdio_init_all();
    sleep_ms(3000);

    printf("\n===== DEBUG PIO TEST =====\n");
    fflush(stdout);

    step("1. stdio + LED init OK");

    float sys_freq = (float)clock_get_hz(clk_sys);
    float divider = sys_freq / (SAMPLE_RATE * 128.0f);
    step("2. clock calc OK");

    PIO pio = pio0;
    step("3. got pio0 OK");

    uint sm = pio_claim_unused_sm(pio, true);
    step("4. claimed SM OK");

    // Minimal PIO program: just NOP (mov y, y) in a tight loop
    // We'll manually define a simple 1-instruction program
    const uint16_t nop_prog[] = { 0xa047 };  // mov y, y (NOP)
    struct pio_program prog = {
        .instructions = nop_prog,
        .length = 1,
        .origin = -1
    };
    uint offset = pio_add_program(pio, &prog);
    step("5. added minimal program OK");

    // Configure SM
    pio_sm_config c = pio_get_default_sm_config();
    sm_config_set_clkdiv(&c, divider);
    pio_sm_init(pio, sm, offset, &c);
    step("6. SM init OK");

    pio_sm_set_enabled(pio, sm, true);
    step("7. SM enabled OK");

    printf("\n===== ALL OK - entering blink loop =====\n");
    fflush(stdout);

    uint64_t last_blink = 0;
    int count = 0;
    while (true) {
        uint64_t now = to_ms_since_boot(get_absolute_time());
        if (now - last_blink > 1000) {
            gpio_put(25, !gpio_get(25));
            last_blink = now;
            printf("tick %d\n", count++);
            fflush(stdout);
        }
        tight_loop_contents();
    }
    return 0;
}
