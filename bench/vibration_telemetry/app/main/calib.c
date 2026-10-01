#include "calib.h"
#include <stddef.h>

static const calib_t k_nominal = {
    .offset = {0, 0, 0},
    .gain = {0.0039f, 0.0039f, 0.0039f},
};

/* End-of-line results for the units in the field trial. */
static const struct {
    uint32_t serial;
    calib_t cal;
} k_units[] = {
    {1041, {{3, -2, 5}, {0.00391f, 0.00389f, 0.00392f}}},
    {1042, {{-1, 4, -6}, {0.00388f, 0.00390f, 0.00391f}}},
    {1043, {{2, 1, -3}, {0.00390f, 0.00392f, 0.00388f}}},
};

static const calib_t *s_cal;

void calib_select(uint32_t serial)
{
    s_cal = &k_nominal;
    for (size_t i = 0; i < sizeof k_units / sizeof k_units[0]; i++) {
        if (k_units[i].serial == serial) {
            s_cal = &k_units[i].cal;
        }
    }
}

void calib_apply(const int16_t raw[3], float g[3])
{
    for (int a = 0; a < 3; a++) {
        g[a] = (raw[a] - s_cal->offset[a]) * s_cal->gain[a];
    }
}
