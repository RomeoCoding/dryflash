/* Tank gauge: a hydrostatic level transmitter (0.5-4.5 V for 0-2000 mm) on AIN0 of an ADS1115
 * (I2C0, SDA 21 / SCL 22, address 0x49). The level is sampled every 100 ms and averaged over
 * 1 s against sloshing; once a second the level and the content are printed. */
#include <stdio.h>
#include "driver/i2c_master.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "ads1115.h"
#include "tank.h"

#define SAMPLE_PERIOD_MS 100
#define AVERAGE_N        10

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0, .sda_io_num = 21, .scl_io_num = 22,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    ESP_ERROR_CHECK(ads1115_init(bus));
    printf("tank gauge started\n");

    float sum = 0;
    int n = 0;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
        float v;
        if (ads1115_read_ain0(&v) != ESP_OK) {
            printf("transmitter read failed\n");
            continue;
        }
        sum += v;
        if (++n < AVERAGE_N) {
            continue;
        }
        uint16_t mm = tank_level_mm(sum / n);
        printf("t=%lu s level=%u mm vol=%u L\n", (unsigned long)(esp_timer_get_time() / 1000000), mm,
               tank_litres(mm));
        sum = 0;
        n = 0;
    }
}
