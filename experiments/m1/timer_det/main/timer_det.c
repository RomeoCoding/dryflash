/*
 * M1 question 4: determinism under -icount. Output depends on the interleaving
 * of an esp_timer callback, two FreeRTOS tasks and the virtual clock, so any
 * host-timing leak shows up as a diff in the UART log.
 */
#include <stdio.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"

static volatile uint32_t s_ticks;

static void timer_cb(void *arg)
{
    s_ticks++;
}

static void worker(void *arg)
{
    const char *name = arg;
    uint32_t acc = 0;
    for (int i = 0; i < 20; i++) {
        for (int j = 0; j < 20000; j++) {
            acc = acc * 1664525u + 1013904223u;
        }
        printf("%s i=%d ticks=%" PRIu32 " t_us=%" PRId64 " acc=%08" PRIx32 "\n",
               name, i, s_ticks, esp_timer_get_time(), acc);
        vTaskDelay(pdMS_TO_TICKS(7));
    }
    printf("%s done\n", name);
    vTaskDelete(NULL);
}

void app_main(void)
{
    const esp_timer_create_args_t args = { .callback = timer_cb, .name = "tick" };
    esp_timer_handle_t t;
    ESP_ERROR_CHECK(esp_timer_create(&args, &t));
    ESP_ERROR_CHECK(esp_timer_start_periodic(t, 1000));
    xTaskCreatePinnedToCore(worker, "A", 4096, "A", 5, NULL, 0);
    xTaskCreatePinnedToCore(worker, "B", 4096, "B", 5, NULL, 1);
    vTaskDelay(pdMS_TO_TICKS(1500));
    printf("TIMER_DET_DONE ticks=%" PRIu32 "\n", s_ticks);
}
