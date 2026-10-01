/* Measurement log: a RAM ring of compact records. The flash writer (not part of this build)
 * drains it in 4 KiB pages, so records are kept small. */
#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct __attribute__((packed)) {
    uint16_t stamp_ms;
    uint16_t rh_x100;  /* 0.01 %RH */
    int16_t temp_x100; /* 0.01 degC */
} log_rec_t;

void log_append(float rh, float temp_c, uint32_t now_ms);
/* Copies the newest record; false while the log is empty. */
bool log_latest(log_rec_t *out);
uint32_t log_count(void);
