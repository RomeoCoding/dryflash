/* Battery monitor: the battery feeds AIN1 of an ADS1115 (I2C0, SDA 21 / SCL 22, address 0x49)
 * through a 2:1 divider. The ADC runs on the +-4.096 V range. Prints the battery voltage every
 * 200 ms and "LOW BATTERY" below 3.4 V. */
#include <stdio.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define ADS1115_ADDR  0x49
#define REG_CONV      0x00
#define REG_CONFIG    0x01
/* OS=1, MUX=101 (AIN1-GND), PGA=001 (+-4.096 V), single-shot, 128 SPS */
#define CONFIG_AIN1   0xD383
#define ADC_FULLSCALE 2.048f
#define DIVIDER       2.0f
#define LOW_BATTERY_V 3.4f

static i2c_master_dev_handle_t s_dev;

static int16_t convert(void)
{
    uint8_t cfg[3] = {REG_CONFIG, CONFIG_AIN1 >> 8, CONFIG_AIN1 & 0xFF};
    ESP_ERROR_CHECK(i2c_master_transmit(s_dev, cfg, 3, 100));
    uint8_t reg = REG_CONFIG, st[2];
    do {
        vTaskDelay(1);
        ESP_ERROR_CHECK(i2c_master_transmit_receive(s_dev, &reg, 1, st, 2, 100));
    } while (!(st[0] & 0x80));
    uint8_t b[2];
    reg = REG_CONV;
    ESP_ERROR_CHECK(i2c_master_transmit_receive(s_dev, &reg, 1, b, 2, 100));
    return (int16_t)(b[0] << 8 | b[1]);
}

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0, .sda_io_num = 21, .scl_io_num = 22,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = ADS1115_ADDR, .scl_speed_hz = 400000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &s_dev));
    printf("battery monitor ready\n");
    for (;;) {
        float vbat = convert() * ADC_FULLSCALE / 32768.0f * DIVIDER;
        printf("battery=%.2f V\n", vbat);
        if (vbat < LOW_BATTERY_V) {
            printf("LOW BATTERY\n");
        }
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}
