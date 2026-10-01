/* TI HDC1080 humidity and temperature sensor: 16-bit big-endian registers behind an 8-bit pointer.
 * Writing the pointer 0x00 starts a conversion; with MODE=1 the part measures temperature, then
 * humidity, and a 4-byte read returns both. */
#include "hdc1080.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define HDC1080_ADDR 0x40
#define REG_TEMP     0x00
#define REG_CONFIG   0x02
#define CONFIG_BOTH  0x1000 /* MODE=1, 14-bit temperature and humidity */

static i2c_master_dev_handle_t s_dev;

esp_err_t hdc1080_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = HDC1080_ADDR, .scl_speed_hz = 100000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &s_dev);
    if (err != ESP_OK) {
        return err;
    }
    uint8_t w[3] = {REG_CONFIG, CONFIG_BOTH >> 8, CONFIG_BOTH & 0xFF};
    return i2c_master_transmit(s_dev, w, sizeof w, 50);
}

esp_err_t hdc1080_read(float *rh, float *temp_c)
{
    uint8_t reg = REG_TEMP, b[4];
    esp_err_t err = i2c_master_transmit(s_dev, &reg, 1, 50);
    if (err != ESP_OK) {
        return err;
    }
    vTaskDelay(pdMS_TO_TICKS(20)); /* 2 x 6.35 ms conversion time at 14 bit */
    err = i2c_master_receive(s_dev, b, sizeof b, 50);
    if (err != ESP_OK) {
        return err;
    }
    *temp_c = (b[0] << 8 | b[1]) * 165.0f / 65536.0f - 40.0f;
    *rh = (b[2] << 8 | b[3]) * 100.0f / 65536.0f;
    return ESP_OK;
}
