#include "lut.h"

uint16_t lut_interp(const lut_point_t *t, size_t n, uint16_t x)
{
    if (x <= t[0].x) {
        return t[0].y;
    }
    if (x >= t[n - 1].x) {
        return t[n - 1].y;
    }
    size_t i = 1;
    while (t[i].x < x) {
        i++;
    }
    const lut_point_t *a = &t[i - 1], *b = &t[i];
    uint16_t frac = ((x - a->x) << 8) / (b->x - a->x); /* position inside the segment, Q8 */
    uint16_t step = (b->y - a->y) * frac;
    return a->y + (step >> 8);
}
