/* Signal statistics: a worker task builds a histogram of 5000 pseudo-random samples and reports
 * the most frequent bin and the mean. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define N_SAMPLES 5000
#define N_BINS    1024

static uint32_t s_seed = 12345;

static uint32_t next_sample(void)
{
    s_seed = s_seed * 1103515245u + 12345u;
    uint32_t a = (s_seed >> 16) & 0x3FF;
    s_seed = s_seed * 1103515245u + 12345u;
    uint32_t b = (s_seed >> 16) & 0x3FF;
    return (a + b) / 2;               /* triangular distribution, peak in the middle */
}

static void compute_stats(void)
{
    uint32_t bins[N_BINS];
    uint64_t sum = 0;

    memset(bins, 0, sizeof(bins));
    for (int i = 0; i < N_SAMPLES; i++) {
        uint32_t v = next_sample();
        bins[v]++;
        sum += v;
        if (i % 1000 == 0) {
            vTaskDelay(1);            /* let other tasks run */
        }
    }
    int peak = 0;
    for (int i = 1; i < N_BINS; i++) {
        if (bins[i] > bins[peak]) {
            peak = i;
        }
    }
    printf("stats: samples=%d mean=%.2f peak_bin=%d peak_count=%lu\n", N_SAMPLES,
           (double)sum / N_SAMPLES, peak, (unsigned long)bins[peak]);
}

static void worker(void *arg)
{
    compute_stats();
    printf("worker done\n");
    vTaskDelete(NULL);
}

void app_main(void)
{
    printf("signal statistics starting\n");
    xTaskCreate(worker, "worker", 2048, NULL, 5, NULL);
}
