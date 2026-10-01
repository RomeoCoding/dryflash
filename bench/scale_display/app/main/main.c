/* Platform scale: a load cell on a NAU7802 bridge ADC (I2C0, SDA 21 / SCL 22, address 0x2A),
 * sampled every 10 ms. The platform is tared at power-up; the display line is refreshed every
 * 100 ms. */
#include <stdio.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "filter.h"
#include "nau7802.h"

#define COUNTS_PER_KG    10000.0f /* load cell calibration at gain 128 */
#define TARE_SAMPLES     32
#define SAMPLE_PERIOD_MS 10
#define DISPLAY_EVERY    10

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0, .sda_io_num = 21, .scl_io_num = 22,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    esp_err_t err = nau7802_init(bus);
    if (err != ESP_OK) {
        printf("scale: NAU7802 not responding (%s)\n", esp_err_to_name(err));
        return;
    }

    int64_t sum = 0;
    for (int i = 0; i < TARE_SAMPLES; i++) {
        int32_t c;
        ESP_ERROR_CHECK(nau7802_read(&c));
        sum += c;
        vTaskDelay(pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
    }
    const float zero = (float)sum / TARE_SAMPLES;
    glitch_filter_reset(0.0f);
    printf("scale ready, zero=%.0f counts\n", zero);

    TickType_t wake = xTaskGetTickCount();
    for (unsigned n = 1;; n++) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
        int32_t c;
        if (nau7802_read(&c) != ESP_OK) {
            printf("scale: read error\n");
            continue;
        }
        float shown = display_average(glitch_filter((c - zero) / COUNTS_PER_KG));
        if (n % DISPLAY_EVERY == 0) {
            printf("weight=%.2f kg\n", shown);
        }
    }
}
