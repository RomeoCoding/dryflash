/* Nuvoton NAU7802 24-bit bridge ADC. */
#include "nau7802.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define NAU7802_ADDR 0x2A
#define REG_PU_CTRL  0x00
#define REG_CTRL1    0x01
#define REG_CTRL2    0x02
#define REG_ADCO_B2  0x12

#define PU_RR  0x01 /* register reset */
#define PU_PUD 0x02 /* power up digital */
#define PU_PUA 0x04 /* power up analog */
#define PU_PUR 0x08 /* power-up ready (read only) */
#define PU_CS  0x10 /* cycle start */
#define PU_CR  0x20 /* cycle ready: a new conversion is waiting (read only) */

#define CTRL1_GAIN_128 0x07
#define CTRL2_80SPS    0x30

static i2c_master_dev_handle_t s_dev;

static esp_err_t reg_write(uint8_t reg, uint8_t val)
{
    uint8_t b[2] = {reg, val};
    return i2c_master_transmit(s_dev, b, 2, 50);
}

static esp_err_t reg_read(uint8_t reg, uint8_t *buf, size_t len)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, buf, len, 50);
}

static esp_err_t wait_bit(uint8_t bit, int max_ticks)
{
    for (int i = 0; i <= max_ticks; i++) {
        uint8_t v;
        esp_err_t err = reg_read(REG_PU_CTRL, &v, 1);
        if (err != ESP_OK) {
            return err;
        }
        if (v & bit) {
            return ESP_OK;
        }
        vTaskDelay(1);
    }
    return ESP_ERR_TIMEOUT;
}

esp_err_t nau7802_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = NAU7802_ADDR, .scl_speed_hz = 400000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &s_dev);
    if (err == ESP_OK) err = reg_write(REG_PU_CTRL, PU_RR);
    if (err == ESP_OK) err = reg_write(REG_PU_CTRL, 0);
    if (err == ESP_OK) err = reg_write(REG_PU_CTRL, PU_PUD | PU_PUA);
    if (err == ESP_OK) err = wait_bit(PU_PUR, 20);
    if (err == ESP_OK) err = reg_write(REG_CTRL1, CTRL1_GAIN_128);
    if (err == ESP_OK) err = reg_write(REG_CTRL2, CTRL2_80SPS);
    if (err == ESP_OK) err = reg_write(REG_PU_CTRL, PU_PUD | PU_PUA | PU_CS);
    return err;
}

esp_err_t nau7802_read(int32_t *counts)
{
    esp_err_t err = wait_bit(PU_CR, 5);
    uint8_t b[3];
    if (err == ESP_OK) {
        err = reg_read(REG_ADCO_B2, b, 3);
    }
    if (err == ESP_OK) {
        int32_t v = (int32_t)((uint32_t)b[0] << 16 | (uint32_t)b[1] << 8 | b[2]);
        *counts = (v ^ 0x800000) - 0x800000; /* sign-extend 24 bits */
    }
    return err;
}
