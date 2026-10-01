#include "log.h"
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define LOG_LEN 128

static log_rec_t s_ring[LOG_LEN];
static uint32_t s_count;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

void log_append(float rh, float temp_c, uint32_t now_ms)
{
    log_rec_t r = {
        .stamp_ms = now_ms,
        .rh_x100 = (uint16_t)lroundf(rh * 100.0f),
        .temp_x100 = (int16_t)lroundf(temp_c * 100.0f),
    };
    portENTER_CRITICAL(&s_lock);
    s_ring[s_count % LOG_LEN] = r;
    s_count++;
    portEXIT_CRITICAL(&s_lock);
}

bool log_latest(log_rec_t *out)
{
    portENTER_CRITICAL(&s_lock);
    bool ok = s_count > 0;
    if (ok) {
        *out = s_ring[(s_count - 1) % LOG_LEN];
    }
    portEXIT_CRITICAL(&s_lock);
    return ok;
}

uint32_t log_count(void)
{
    return s_count;
}
