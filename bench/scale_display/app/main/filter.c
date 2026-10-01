#include "filter.h"
#include <math.h>

/* A knock on the platform, or the conveyor relay switching next to the load cell cable, gives a
 * few wild readings; a real load change persists. */
#define GLITCH_KG 1.0f
#define CONFIRM_N 5 /* 50 ms at the 10 ms sample period */
#define AVG_N     8

static float s_accepted;
static float s_candidate;
static int s_confirm;

void glitch_filter_reset(float kg)
{
    s_accepted = kg;
    s_confirm = 0;
}

float glitch_filter(float kg)
{
    if (fabsf(kg - s_accepted) <= GLITCH_KG) {
        /* small change: load settling or creeping, follow it */
        s_confirm = 0;
        s_accepted = kg;
        return kg;
    }
    if (s_confirm == 0) {
        s_candidate = kg;
    }
    if (fabsf(kg - s_candidate) <= GLITCH_KG && ++s_confirm >= CONFIRM_N) {
        s_confirm = 0;
        s_accepted = kg;
    }
    return s_accepted;
}

float display_average(float kg)
{
    static float ring[AVG_N];
    static float sum;
    static int pos, filled;
    sum += kg - ring[pos];
    ring[pos] = kg;
    pos = (pos + 1) % AVG_N;
    if (filled < AVG_N) {
        filled++;
    }
    return sum / filled;
}
