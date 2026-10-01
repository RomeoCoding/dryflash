#pragma once
#include <stdint.h>

/* Per-unit calibration, measured at end-of-line test: zero-g offset (LSB) and gain (g/LSB). */
typedef struct {
    int16_t offset[3];
    float gain[3];
} calib_t;

/* Selects the calibration set for this unit's serial number (0: nominal). */
void calib_select(uint32_t serial);
/* Converts one raw sample to g. */
void calib_apply(const int16_t raw[3], float g[3]);
