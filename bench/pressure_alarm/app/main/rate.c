#include "rate.h"

static float s_x[RATE_WINDOW];
static int s_pos, s_filled;
static float s_denominator; /* sum over the window of (t_i - t_mean)^2, in s^2 */
static float s_dt;

void rate_init(float sample_period_s)
{
    s_dt = sample_period_s;
    s_denominator = 0;
    for (int i = 0; i < RATE_WINDOW; i++) {
        float d = (i - (RATE_WINDOW - 1) / 2.0f) * s_dt;
        s_denominator += d * d;
    }
    s_pos = s_filled = 0;
}

float rate_update(float x)
{
    s_x[s_pos] = x;
    s_pos = (s_pos + 1) % RATE_WINDOW;
    if (s_filled < RATE_WINDOW) {
        s_filled++;
        return 0.0f;
    }
    float mean = 0;
    for (int i = 0; i < RATE_WINDOW; i++) {
        mean += s_x[i];
    }
    mean /= RATE_WINDOW;
    float num = 0;
    for (int i = 0; i < RATE_WINDOW; i++) {
        /* oldest sample first: s_pos now points at it */
        float d = (i - (RATE_WINDOW - 1) / 2.0f) * s_dt;
        num += d * (s_x[(s_pos + i) % RATE_WINDOW] - mean);
    }
    return num / s_denominator;
}
