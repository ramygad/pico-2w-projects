/*
 * Minimal test firmware — blink GP25 LED + serial output
 * Use this to verify the Pico 2W is alive after flashing.
 */
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"

#define LED_PIN 25   // Pico 2W onboard LED (GP25)

int main(void) {
    stdio_init_all();
    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);

    // Blink rapidly for 5 seconds to show we're alive
    for (int i = 0; i < 25; i++) {
        gpio_put(LED_PIN, 1);
        sleep_ms(100);
        gpio_put(LED_PIN, 0);
        sleep_ms(100);
    }

    printf("\n============================================\n");
    printf("  Pico 2W — TEST FIRMWARE\n");
    printf("============================================\n");
    printf("  Alive and printing!\n");

    while (true) {
        gpio_put(LED_PIN, 1);
        printf(".");
        fflush(stdout);
        sleep_ms(500);
        gpio_put(LED_PIN, 0);
        sleep_ms(500);
    }

    return 0;
}
