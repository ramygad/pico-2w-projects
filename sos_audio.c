/*
 * Pico 2W — I2S S.O.S. Audio Tone Flasher
 * =========================================
 * Generates an S.O.S. Morse pattern as an audio tone
 * through a GY-PCM5102 DAC connected via I2S.
 *
 * Wiring:
 *   PCM5102 BCK -> Pico GP10
 *   PCM5102 LCK -> Pico GP11
 *   PCM5102 DIN -> Pico GP12
 *   PCM5102 VIN -> 3.3V or 5V
 *   PCM5102 GND -> GND
 *   PCM5102 XMT -> 3.3V (unmute)
 *   PCM5102 FMT -> GND (I2S mode)
 *   PCM5102 SCK -> NC (internal PLL)
 *
 * Build:  cmake -B build -G Ninja -DPICO_BOARD=pico2_w && ninja -C build
 * Flash:  copy build/sos_audio.uf2 to Pico in BOOTSEL mode
 */

#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "i2s_audio.pio.h"

// ── Pin assignments ──────────────────────────────────────────────────
#define PIN_BCK    10
#define PIN_LCK    11
#define PIN_DIN    12

// ── Audio parameters ─────────────────────────────────────────────────
#define SAMPLE_RATE     48000       // Hz
#define TONE_FREQ       800         // Hz (nice audible tone)
#define AMPLITUDE       12000       // 16-bit signed amplitude (0-32767)

// ── SOS timing (milliseconds) ────────────────────────────────────────
#define DOT_MS          200         // short blip
#define DASH_MS         600         // long blip
#define GAP_MS          180         // inter-element gap (within letter)
#define LETTER_GAP_MS   400         // gap between letters
#define REPEAT_GAP_MS   1200        // gap between SOS repeats

#define MS_TO_SAMPLES(ms)  ((ms) * SAMPLE_RATE / 1000)

// ── S.O.S. state machine ─────────────────────────────────────────────
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
    int         samples;       // samples to stay in this state
    bool        tone_on;       // produce tone or silence
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

// ── Entry point ──────────────────────────────────────────────────────
int main(void) {
    // Heartbeat LED on GP25 — init BEFORE stdio
    gpio_init(25);
    gpio_set_dir(25, GPIO_OUT);
    gpio_put(25, 1);

    stdio_init_all();

    sleep_ms(500);      // short wait for USB CDC, then print
    printf("\n============================================\n");
    printf("  Pico 2W — I2S S.O.S. Audio Flasher\n");
    printf("============================================\n");
    printf("  BCK:     GP%d\n", PIN_BCK);
    printf("  LCK:     GP%d\n", PIN_LCK);
    printf("  DIN:     GP%d\n", PIN_DIN);
    printf("  Sample:  %d Hz\n", SAMPLE_RATE);
    printf("  Tone:    %d Hz\n", TONE_FREQ);
    printf("--------------------------------------------\n");
    fflush(stdout);

    // ── Compute PIO clock divider ──────────────────────
    float sys_freq = (float)clock_get_hz(clk_sys);
    float divider  = sys_freq / (SAMPLE_RATE * 128.0f);
    printf("  Sys clk: %.0f Hz\n", sys_freq);
    printf("  Divider: %.3f\n", divider);
    fflush(stdout);

    // ── Claim PIO resources ────────────────────────────
    PIO  pio    = pio0;
    uint sm     = pio_claim_unused_sm(pio, true);
    uint offset = pio_add_program(pio, &i2s_audio_program);

    // ── Initialise I2S PIO ─────────────────────────────
    i2s_audio_init(pio, sm, offset, PIN_BCK, PIN_LCK, PIN_DIN, divider);
    printf("  I2S PIO running.\n\n");
    fflush(stdout);

    // Brief delay & flush to let USB serial catch up
    {
        int _di = 0;
        while (_di < 5) {
            _di++;
            sleep_ms(200);
            printf(".");
            fflush(stdout);
        }
    }
    printf(" GO\n");
    fflush(stdout);

    // ── S.O.S. audio loop ──────────────────────────────
    sos_state_t state   = S_DOT1;
    int         samples_in_state = 0;
    uint64_t    sample_counter   = 0;

    // Precompute square-wave half-period in samples
    int half_cycle = SAMPLE_RATE / TONE_FREQ / 2;

    while (true) {
        // ── LED follows the S.O.S. tone pattern ─────────
        gpio_put(25, sos_fsm[state].tone_on);

        // ── Generate one stereo sample ─────────────────
        // Square wave: high for half cycle, low for half cycle
        int16_t raw;
        if (sos_fsm[state].tone_on) {
            int pos = (int)(sample_counter % (uint64_t)(half_cycle * 2));
            raw = (pos < half_cycle) ? (int16_t)AMPLITUDE : (int16_t)(-AMPLITUDE);
        } else {
            raw = 0;
        }

        // Pack: 16-bit sample in upper half of 32-bit word (left-justified)
        uint32_t word = (uint32_t)(uint16_t)raw << 16;

        // Push left channel + right channel (mono duplicated)
        pio_sm_put_blocking(pio, sm, word);
        pio_sm_put_blocking(pio, sm, word);

        sample_counter++;
        samples_in_state++;

        // ── Advance SOS state machine ──────────────────
        if (samples_in_state >= sos_fsm[state].samples) {
            samples_in_state = 0;
            state = sos_fsm[state].next;
        }
    }

    return 0;   // unreachable
}
