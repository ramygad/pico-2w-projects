/*
 * Ultra-minimal test — just LED and serial, no PIO
 */
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"

int main(void) {
    gpio_init(25);
    gpio_set_dir(25, GPIO_OUT);
    gpio_put(25, 1);  // LED on immediately

    stdio_init_all();

    // Short wait, then print
    sleep_ms(500);
    printf("Hello from Pico 2W!\n");
    fflush(stdout);

    gpio_put(25, 0);
    sleep_ms(200);
    gpio_put(25, 1);
    
    printf("USB serial alive.\n");
    fflush(stdout);

    uint64_t last = 0;
    int count = 0;
    while (true) {
        uint64_t now = to_ms_since_boot(get_absolute_time());
        if (now - last > 1000) {
            gpio_put(25, !gpio_get(25));
            last = now;
            printf("tick %d\n", count++);
            fflush(stdout);
        }
        tight_loop_contents();
    }
    return 0;
}
