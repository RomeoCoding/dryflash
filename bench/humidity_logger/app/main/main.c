/* Humidity logger: an HDC1080 (I2C0, SDA 21 / SCL 22, address 0x40) is sampled every 250 ms into
 * the measurement log; once a second the newest record is published on the console. */
#include <stdio.h>
#include "driver/i2c_master.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hdc1080.h"
#include "log.h"

#define SAMPLE_PERIOD_MS  250
#define PUBLISH_PERIOD_MS 1000
#define STALE_MS          2000 /* no record for this long means the sensor task is stuck */
#define MAX_I2C_FAILURES  3

static uint32_t uptime_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static void sensor_task(void *arg)
{
    int failures = 0;
    for (;;) {
        float rh, temp_c;
        if (hdc1080_read(&rh, &temp_c) == ESP_OK) {
            failures = 0;
            log_append(rh, temp_c, uptime_ms());
        } else if (++failures == MAX_I2C_FAILURES) {
            printf("sensor fault: i2c\n");
        }
        vTaskDelay(pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
    }
}

static void publish_task(void *arg)
{
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(PUBLISH_PERIOD_MS));
        log_rec_t rec;
        uint32_t now = uptime_ms();
        if (!log_latest(&rec) || now - rec.stamp_ms > STALE_MS) {
            printf("sensor fault: no fresh data\n");
            continue;
        }
        printf("t=%lu s rh=%.1f %% temp=%.1f C (%lu records)\n", (unsigned long)(now / 1000),
               rec.rh_x100 / 100.0, rec.temp_x100 / 100.0, (unsigned long)log_count());
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
    ESP_ERROR_CHECK(hdc1080_init(bus));
    printf("humidity logger started\n");
    xTaskCreate(sensor_task, "sensor", 3072, NULL, 5, NULL);
    xTaskCreate(publish_task, "publish", 3072, NULL, 4, NULL);
}
