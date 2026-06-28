cmake_minimum_required(VERSION 3.22)

# Pull in the Pico SDK
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

# Project definition
project(sos_flasher C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the SDK
pico_sdk_init()

# ── Original LED S.O.S. flasher ──────────────────────────────────────
add_executable(sos_flasher
    sos_flasher.c
)

target_link_libraries(sos_flasher
    pico_stdlib
    pico_cyw43_arch_none
)

pico_enable_stdio_usb(sos_flasher 1)
pico_enable_stdio_uart(sos_flasher 0)
pico_add_extra_outputs(sos_flasher)

# ── I2S Audio S.O.S. tone flasher ────────────────────────────────────
add_executable(sos_audio
    sos_audio.c
)

# Generate PIO header from .pio file (must be after add_executable)
pico_generate_pio_header(sos_audio ${CMAKE_CURRENT_LIST_DIR}/i2s_audio.pio)

target_link_libraries(sos_audio
    pico_stdlib
    hardware_pio
)

pico_enable_stdio_usb(sos_audio 1)
pico_enable_stdio_uart(sos_audio 0)
pico_add_extra_outputs(sos_audio)

# ── Test: minimal alive check ──────────────────────────────────────────
add_executable(test_alive
    test_alive.c
)

target_link_libraries(test_alive
    pico_stdlib
)

pico_enable_stdio_usb(test_alive 1)
pico_enable_stdio_uart(test_alive 0)
pico_add_extra_outputs(test_alive)

# ── Debug: PIO init test ──────────────────────────────────────────────
add_executable(debug_pio
    debug_pio.c
)

target_link_libraries(debug_pio
    pico_stdlib
    hardware_pio
)

pico_enable_stdio_usb(debug_pio 1)
pico_enable_stdio_uart(debug_pio 0)
pico_add_extra_outputs(debug_pio)

# ── Debug: I2S PIO step-by-step ───────────────────────────────────────
add_executable(debug_i2s
    debug_i2s.c
)

pico_generate_pio_header(debug_i2s ${CMAKE_CURRENT_LIST_DIR}/i2s_audio.pio)

target_link_libraries(debug_i2s
    pico_stdlib
    hardware_pio
)

pico_enable_stdio_usb(debug_i2s 1)
pico_enable_stdio_uart(debug_i2s 0)
pico_add_extra_outputs(debug_i2s)

# ── Debug: I2S PIO step-by-step v2 (immediate print) ──────────────────
add_executable(debug_i2s2
    debug_i2s2.c
)

pico_generate_pio_header(debug_i2s2 ${CMAKE_CURRENT_LIST_DIR}/i2s_audio.pio)

target_link_libraries(debug_i2s2
    pico_stdlib
    hardware_pio
)

pico_enable_stdio_usb(debug_i2s2 1)
pico_enable_stdio_uart(debug_i2s2 0)
pico_add_extra_outputs(debug_i2s2)

# ── Debug: SOS loop test ──────────────────────────────────────────────
add_executable(debug_sos
    debug_sos.c
)

pico_generate_pio_header(debug_sos ${CMAKE_CURRENT_LIST_DIR}/i2s_audio.pio)

target_link_libraries(debug_sos
    pico_stdlib
    hardware_pio
)

pico_enable_stdio_usb(debug_sos 1)
pico_enable_stdio_uart(debug_sos 0)
pico_add_extra_outputs(debug_sos)

# Board set via -DPICO_BOARD=pico2_w on cmake command line
