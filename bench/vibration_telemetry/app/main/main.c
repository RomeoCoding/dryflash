/* Vibration logger: an ADXL345 (I2C0, SDA 21 / SCL 22, address 0x53) on the machine housing is
 * sampled every 10 ms. Each second, the sampler hands a summary to the telemetry task, which
 * sends it as one radio frame (printed on the console as "tx <frame>"). */
#include <math.h>
#include <stdio.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "adxl345.h"
#include "calib.h"
#include "telemetry.h"

#define UNIT_SERIAL       1042
#define SAMPLE_PERIOD_MS  10
#define SAMPLES_PER_FRAME 100

static QueueHandle_t s_summaries;

static void sampler_task(void *arg)
{
    summary_t s = {0};
    double sum_sq = 0;
    int n = 0;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
        int16_t raw[3];
        if (adxl345_read_raw(raw) != ESP_OK) {
            continue;
        }
        float g[3];
        calib_apply(raw, g);
        for (int a = 0; a < 3; a++) {
            if (n == 0 || g[a] < s.min[a]) s.min[a] = g[a];
            if (n == 0 || g[a] > s.max[a]) s.max[a] = g[a];
        }
        sum_sq += g[0] * g[0] + g[1] * g[1] + g[2] * g[2];
        if (++n == SAMPLES_PER_FRAME) {
            s.rms = sqrt(sum_sq / n);
            xQueueSend(s_summaries, &s, 0);
            s.seq++;
            sum_sq = 0;
            n = 0;
        }
    }
}

static void telemetry_task(void *arg)
{
    summary_t s;
    for (;;) {
        if (xQueueReceive(s_summaries, &s, portMAX_DELAY) == pdTRUE) {
            printf("tx %s\n", telemetry_frame(&s));
        }
    }
}

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0, .sda_io_num = 21, .scl_io_num = 22,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    ESP_ERROR_CHECK(adxl345_init(bus));
    calib_select(UNIT_SERIAL);
    s_summaries = xQueueCreate(4, sizeof(summary_t));
    printf("vibration logger, unit %d\n", UNIT_SERIAL);
    xTaskCreate(sampler_task, "sampler", 4096, NULL, 6, NULL);
    xTaskCreate(telemetry_task, "telemetry", 4096, NULL, 4, NULL);
}
