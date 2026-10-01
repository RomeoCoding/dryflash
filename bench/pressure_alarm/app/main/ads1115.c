/* TI ADS1115 16-bit ADC, single-shot conversions at 860 SPS (1.2 ms). */
#include "ads1115.h"
#include "rom/ets_sys.h"

#define ADS1115_ADDR 0x49
#define REG_CONV     0x00
#define REG_CONFIG   0x01
/* OS=1 (start), MUX=100 (AIN0-GND), PGA=000 (+-6.144 V), single-shot, 860 SPS */
#define CONFIG_AIN0  0xC1E3
#define FULL_SCALE_V 6.144f

static i2c_master_dev_handle_t s_dev;

esp_err_t ads1115_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = ADS1115_ADDR, .scl_speed_hz = 400000,
    };
    return i2c_master_bus_add_device(bus, &cfg, &s_dev);
}

esp_err_t ads1115_read_ain0(float *volts)
{
    uint8_t cfg[3] = {REG_CONFIG, CONFIG_AIN0 >> 8, CONFIG_AIN0 & 0xFF};
    esp_err_t err = i2c_master_transmit(s_dev, cfg, 3, 50);
    uint8_t reg = REG_CONFIG, b[2] = {0};
    for (int tries = 0; err == ESP_OK && !(b[0] & 0x80); tries++) { /* OS=1: conversion done */
        if (tries == 10) {
            return ESP_ERR_TIMEOUT;
        }
        ets_delay_us(300);
        err = i2c_master_transmit_receive(s_dev, &reg, 1, b, 2, 50);
    }
    reg = REG_CONV;
    if (err == ESP_OK) {
        err = i2c_master_transmit_receive(s_dev, &reg, 1, b, 2, 50);
    }
    if (err == ESP_OK) {
        *volts = (int16_t)(b[0] << 8 | b[1]) * FULL_SCALE_V / 32768.0f;
    }
    return err;
}
