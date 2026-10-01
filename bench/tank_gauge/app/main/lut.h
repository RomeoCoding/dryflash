#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint16_t x, y;
} lut_point_t;

/* Piecewise-linear lookup in a table sorted by x; clamps outside the table. Integer arithmetic
 * only: the same code runs on the display board's 8-bit MCU. */
uint16_t lut_interp(const lut_point_t *t, size_t n, uint16_t x);
