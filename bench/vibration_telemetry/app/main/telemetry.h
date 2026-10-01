#pragma once
#include <stdint.h>

/* One second of vibration: per-axis minimum and maximum, and the RMS of the vector magnitude. */
typedef struct {
    uint32_t seq;
    float min[3], max[3];
    float rms;
} summary_t;

/* Formats the radio frame for one summary and returns it (valid until the next call):
 * "T<seq> x<min>/<max> y<min>/<max> z<min>/<max> r<rms>*<checksum>" */
const char *telemetry_frame(const summary_t *s);
