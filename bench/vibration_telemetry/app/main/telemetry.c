#include "telemetry.h"
#include <stdio.h>

#define FRAME_LEN 64

static char s_frame[FRAME_LEN];

/* NMEA-style checksum: XOR of every character before the '*'. */
static uint8_t checksum(const char *p, size_t n)
{
    uint8_t c = 0;
    while (n--) {
        c ^= (uint8_t)*p++;
    }
    return c;
}

const char *telemetry_frame(const summary_t *s)
{
    static const char axis[3] = {'x', 'y', 'z'};
    size_t off = snprintf(s_frame, sizeof s_frame, "T%05lu", (unsigned long)s->seq);
    for (int a = 0; a < 3; a++) {
        off += snprintf(s_frame + off, sizeof s_frame - off, " %c%+.3f/%+.3f", axis[a], s->min[a], s->max[a]);
    }
    off += snprintf(s_frame + off, sizeof s_frame - off, " r%.3f", s->rms);
    snprintf(s_frame + off, sizeof s_frame - off, "*%02X", checksum(s_frame, off));
    return s_frame;
}
