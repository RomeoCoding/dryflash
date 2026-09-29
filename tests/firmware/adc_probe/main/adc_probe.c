/*
 * adc_probe: ADS1115 driver exercise for the sensor-injection tests. Single-shot conversions on
 * several MUX/PGA settings (bank selection), OS-bit polling (read-set) and 16-bit registers
 * (stride 2), then AIN0 every 100 ms so tests can watch mid-run changes.
 */
#include <stdio.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define ADS1115_ADDR 0x49
#define REG_CONV     0x00
#define REG_CONFIG   0x01

static i2c_master_dev_handle_t s_dev;

static uint16_t reg_read16(uint8_t reg)
{
    uint8_t b[2] = {0};
    ESP_ERROR_CHECK(i2c_master_transmit_receive(s_dev, &reg, 1, b, 2, 100));
    return (uint16_t)(b[0] << 8 | b[1]);
}

static void reg_write16(uint8_t reg, uint16_t v)
{
    uint8_t b[3] = {reg, v >> 8, v & 0xff};
    ESP_ERROR_CHECK(i2c_master_transmit(s_dev, b, 3, 100));
}

/* mux: 0..7 as in the datasheet, pga: 0..7; returns volts */
static float convert(int mux, int pga, int16_t *code_out)
{
    static const float fs[8] = {6.144f, 4.096f, 2.048f, 1.024f, 0.512f, 0.256f, 0.256f, 0.256f};
    uint16_t cfg = 0x8000 | mux << 12 | pga << 9 | 0x0100 | 0x0080 | 0x0003; /* OS, single-shot, 128 SPS */
    reg_write16(REG_CONFIG, cfg);
    while (!(reg_read16(REG_CONFIG) & 0x8000)) {
        vTaskDelay(1);
    }
    int16_t code = (int16_t)reg_read16(REG_CONV);
    *code_out = code;
    return code * fs[pga] / 32768.0f;
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

    printf("config at reset: 0x%04x\n", reg_read16(REG_CONFIG));
    printf("lo_thresh 0x%04x hi_thresh 0x%04x\n", reg_read16(0x02), reg_read16(0x03));
    int16_t code;
    float v = convert(4, 1, &code);
    printf("ain0 pga4.096 code=%d v=%.4f\n", code, v);
    v = convert(4, 2, &code);
    printf("ain0 pga2.048 code=%d v=%.4f\n", code, v);
    v = convert(0, 2, &code);
    printf("ain0-ain1 pga2.048 code=%d v=%.4f\n", code, v);
    v = convert(7, 2, &code);
    printf("ain3 pga2.048 code=%d v=%.4f\n", code, v);
    for (int i = 0;; i++) {
        v = convert(4, 1, &code);
        printf("tick %d ain0=%.4f\n", i, v);
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
