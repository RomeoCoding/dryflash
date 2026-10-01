#pragma once

/* Rate of change of an evenly sampled signal: least-squares slope over the last RATE_WINDOW
 * samples, which is far less noisy than a two-point difference. */
#define RATE_WINDOW 8

void rate_init(float sample_period_s);
/* Adds one sample; returns the slope in units per second (0 until the window is full). */
float rate_update(float x);
