/*
 * Hybrid test: working I2S PIO init + SOS main loop
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
#define TONE_FREQ   800
#define AMPLITUDE   12000

#define DOT_MS          200
#define DASH_MS         600
#define GAP_MS          180
#define LETTER_GAP_MS   400
#define REPEAT_GAP_MS   1200
#define MS_TO_SAMPLES(ms)  ((ms) * SAMPLE_RATE / 1000)

typedef enum {
    S_DOT1, S_GAP1, S_DOT2, S_GAP2, S_DOT3,
    S_LGAP1,
    S_DASH1, S_GAP3, S_DASH2, S_GAP4, S_DASH3,
    S_LGAP2,
    S_DOT4, S_GAP5, S_DOT5, S_GAP6, S_DOT6,
    S_RGAP
} sos_state_t;

static const struct {
    sos_state_t next;
    int         samples;
    bool        tone_on;
} sos_fsm[] = {
    [S_DOT1]   = { S_GAP1,   MS_TO_SAMPLES(DOT_MS),         true  },
    [S_GAP1]   = { S_DOT2,   MS_TO_SAMPLES(GAP_MS),         false },
    [S_DOT2]   = { S_GAP2,   MS_TO_SAMPLES(DOT_MS),         true  },
    [S_GAP2]   = { S_DOT3,   MS_TO_SAMPLES(GAP_MS),         false },
    [S_DOT3]   = { S_LGAP1,  MS_TO_SAMPLES(DOT_MS),         true  },
    [S_LGAP1]  = { S_DASH1,  MS_TO_SAMPLES(LETTER_GAP_MS),  false },
    [S_DASH1]  = { S_GAP3,   MS_TO_SAMPLES(DASH_MS),        true  },
    [S_GAP3]   = { S_DASH2,  MS_TO_SAMPLES(GAP_MS),         false },
    [S_DASH2]  = { S_GAP4,   MS_TO_SAMPLES(DASH_MS),        true  },
    [S_GAP4]   = { S_DASH3,  MS_TO_SAMPLES(GAP_MS),         false },
    [S_DASH3]  = { S_LGAP2,  MS_TO_SAMPLES(DASH_MS),        true  },
    [S_LGAP2]  = { S_DOT4,   MS_TO_SAMPLES(LETTER_GAP_MS),  false },
    [S_DOT4]   = { S_GAP5,   MS_TO_SAMPLES(DOT_MS),         true  },
    [S_GAP5]   = { S_DOT5,   MS_TO_SAMPLES(GAP_MS),         false },
    [S_DOT5]   = { S_GAP6,   MS_TO_SAMPLES(DOT_MS),         true  },
    [S_GAP6]   = { S_DOT6,   MS_TO_SAMPLES(GAP_MS),         false },
    [S_DOT6]   = { S_RGAP,   MS_TO_SAMPLES(DOT_MS),         true  },
    [S_RGAP]   = { S_DOT1,   MS_TO_SAMPLES(REPEAT_GAP_MS),  false },
};

int main(void) {
    gpio_init(25);
    gpio_set_dir(25, GPIO_OUT);
    gpio_put(25, 1);

    stdio_init_all();

    // Immediate boot message
    printf("BOOT\n");
    fflush(stdout);
    sleep_ms(200);

    float sys_freq = (float)clock_get_hz(clk_sys);
    float divider  = sys_freq / (SAMPLE_RATE * 128.0f);
    printf("FREQ %.0f DIV %.3f\n", sys_freq, divider);
    fflush(stdout);

    PIO  pio    = pio0;
    uint sm     = pio_claim_unused_sm(pio, true);
    uint offset = pio_add_program(pio, &i2s_audio_program);
    printf("PIO sm=%u offset=%u\n", sm, offset);
    fflush(stdout);

    pio_gpio_init(pio, PIN_BCK);
    pio_gpio_init(pio, PIN_LCK);
    pio_gpio_init(pio, PIN_DIN);
    printf("GPIO_INIT done\n");
    fflush(stdout);

    pio_sm_config c = i2s_audio_program_get_default_config(offset);
    sm_config_set_sideset_pins(&c, PIN_BCK);
    sm_config_set_out_pins(&c, PIN_DIN, 1);
    sm_config_set_out_shift(&c, true, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_clkdiv(&c, divider);
    printf("SM_CONFIG done\n");
    fflush(stdout);

    pio_sm_set_consecutive_pindirs(pio, sm, PIN_BCK, 2, true);
    pio_sm_set_consecutive_pindirs(pio, sm, PIN_DIN, 1, true);
    printf("PINDIRS done\n");
    fflush(stdout);

    pio_sm_init(pio, sm, offset, &c);
    printf("SM_INIT done\n");
    fflush(stdout);

    pio_sm_set_enabled(pio, sm, true);
    printf("SM_ENABLED — starting SOS loop\n");
    fflush(stdout);
    
    // Wait 2 more seconds for USB to flush before tight loop
    for (int i = 0; i < 10; i++) {
        sleep_ms(200);
        printf(".");
        fflush(stdout);
    }
    printf("\nGO\n");
    fflush(stdout);

    // ── SOS loop (same as sos_audio.c) ────────────────
    sos_state_t state   = S_DOT1;
    int         samples_in_state = 0;
    uint64_t    sample_counter   = 0;
    int half_cycle = SAMPLE_RATE / TONE_FREQ / 2;
    int tick_count = 0;

    while (true) {
        // Print alive periodically
        if (tick_count > 0 && tick_count % 480000 == 0) {
            printf("alive %d\n", tick_count);
            fflush(stdout);
        }

        int16_t raw;
        if (sos_fsm[state].tone_on) {
            int pos = (int)(sample_counter % (uint64_t)(half_cycle * 2));
            raw = (pos < half_cycle) ? (int16_t)AMPLITUDE : (int16_t)(-AMPLITUDE);
        } else {
            raw = 0;
        }
        uint32_t word = (uint32_t)(uint16_t)raw << 16;
        pio_sm_put_blocking(pio, sm, word);
        pio_sm_put_blocking(pio, sm, word);
        sample_counter++;
        samples_in_state++;
        if (samples_in_state >= sos_fsm[state].samples) {
            samples_in_state = 0;
            state = sos_fsm[state].next;
        }
        tick_count++;
        if (tick_count % 48000 == 0) {  // every ~1 second
            gpio_put(25, !gpio_get(25));
        }
    }
    return 0;
}
