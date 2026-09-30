/* Heartbeat monitor: a periodic timer should beat every 100 ms; the app reports the beat count
 * every second of uptime. */
#include <stdio.h>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define HEARTBEAT_PERIOD_MS 100

static volatile int s_beats;

static void heartbeat(void *arg)
{
    s_beats++;
}

void app_main(void)
{
    const esp_timer_create_args_t args = {.callback = heartbeat, .name = "heartbeat"};
    esp_timer_handle_t t;
    ESP_ERROR_CHECK(esp_timer_create(&args, &t));
    ESP_ERROR_CHECK(esp_timer_start_periodic(t, HEARTBEAT_PERIOD_MS));
    printf("heartbeat every %d ms\n", HEARTBEAT_PERIOD_MS);
    for (int s = 1; s <= 3; s++) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        printf("uptime %d s beats=%d\n", s, s_beats);
    }
}
