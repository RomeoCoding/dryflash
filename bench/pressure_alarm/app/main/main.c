/* Hydraulic line monitor: a 0-10 bar pressure transmitter (0.5-4.5 V) on AIN0 of an ADS1115
 * (I2C0, SDA 21 / SCL 22, address 0x49). A pressure rise of 5 bar/s or more, sustained for three
 * samples, means a valve slammed shut: raise the rapid-rise alarm. */
#include <stdbool.h>
#include <stdio.h>
#include "driver/i2c_master.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "ads1115.h"
#include "rate.h"

#define SAMPLE_PERIOD_MS 15  /* 66.7 Hz */
#define STATUS_PERIOD_MS 500
#define RISE_ALARM_BAR_S 5.0f
#define RISE_CLEAR_BAR_S 1.0f
#define RISE_CONFIRM     3
#define DISPLAY_ALPHA    0.2f /* smoothing of the displayed pressure only */

static float volts_to_bar(float v)
{
    return (v - 0.5f) * (10.0f / 4.0f);
}

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0, .sda_io_num = 21, .scl_io_num = 22,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    ESP_ERROR_CHECK(ads1115_init(bus));
    rate_init(SAMPLE_PERIOD_MS / 1000.0f);
    printf("pressure monitor started, rise alarm at %.1f bar/s\n", RISE_ALARM_BAR_S);

    float shown = -1.0f;
    int over = 0, alarms = 0;
    bool alarm = false;
    int64_t next_status_us = 0;
    for (;;) {
        float v;
        if (ads1115_read_ain0(&v) != ESP_OK) {
            printf("adc read failed\n");
            vTaskDelay(pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
            continue;
        }
        float bar = volts_to_bar(v);
        float rate = rate_update(bar);
        shown = shown < 0 ? bar : shown + DISPLAY_ALPHA * (bar - shown);
        int64_t now_us = esp_timer_get_time();

        over = rate >= RISE_ALARM_BAR_S ? over + 1 : 0;
        if (!alarm && over >= RISE_CONFIRM) {
            alarm = true;
            alarms++;
            printf("ALARM: rapid pressure rise (%.2f bar/s) at t=%lld ms\n", rate, now_us / 1000);
        } else if (alarm && rate < RISE_CLEAR_BAR_S) {
            alarm = false;
            printf("alarm cleared at t=%lld ms\n", now_us / 1000);
        }
        if (now_us >= next_status_us) {
            printf("t=%.1f s p=%.2f bar rate=%.2f bar/s alarms=%d\n", now_us / 1e6, shown, rate, alarms);
            next_status_us = (now_us / 1000 / STATUS_PERIOD_MS + 1) * STATUS_PERIOD_MS * 1000LL;
        }
        vTaskDelay(pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
    }
}
