/* Measurement sequencer: waits for a 6-second warm-up timer, then takes 5 measurements. */
#include <stdbool.h>
#include <stdio.h>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static volatile bool s_warm;

static void warmup_done(void *arg)
{
    s_warm = true;
}

static int measure(int i)
{
    return 1000 + i * 17;
}

static void sequencer(void *arg)
{
    printf("warming up sensor front-end (6 s)\n");
    while (!s_warm) {
        /* wait for the warm-up timer */
    }
    for (int i = 0; i < 5; i++) {
        printf("measurement %d: %d\n", i, measure(i));
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    printf("measurement complete\n");
    vTaskDelete(NULL);
}

void app_main(void)
{
    const esp_timer_create_args_t args = {.callback = warmup_done, .name = "warmup"};
    esp_timer_handle_t t;
    ESP_ERROR_CHECK(esp_timer_create(&args, &t));
    ESP_ERROR_CHECK(esp_timer_start_once(t, 6 * 1000 * 1000));
    xTaskCreatePinnedToCore(sequencer, "sequencer", 4096, NULL, 5, NULL, 0);
}
