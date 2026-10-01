#include "adxl345.h"

#define ADXL345_ADDR    0x53
#define REG_DEVID       0x00
#define REG_BW_RATE     0x2C
#define REG_POWER_CTL   0x2D
#define REG_DATA_FORMAT 0x31
#define REG_DATAX0      0x32

static i2c_master_dev_handle_t s_dev;

static esp_err_t reg_write(uint8_t reg, uint8_t val)
{
    uint8_t b[2] = {reg, val};
    return i2c_master_transmit(s_dev, b, 2, 50);
}

esp_err_t adxl345_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = ADXL345_ADDR, .scl_speed_hz = 400000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &s_dev);
    uint8_t reg = REG_DEVID, id = 0;
    if (err == ESP_OK) err = i2c_master_transmit_receive(s_dev, &reg, 1, &id, 1, 50);
    if (err == ESP_OK && id != 0xE5) err = ESP_ERR_NOT_FOUND;
    if (err == ESP_OK) err = reg_write(REG_BW_RATE, 0x0C);     /* 400 Hz */
    if (err == ESP_OK) err = reg_write(REG_DATA_FORMAT, 0x0B); /* FULL_RES, +-16 g */
    if (err == ESP_OK) err = reg_write(REG_POWER_CTL, 0x08);   /* measure */
    return err;
}

esp_err_t adxl345_read_raw(int16_t raw[3])
{
    uint8_t reg = REG_DATAX0, b[6];
    esp_err_t err = i2c_master_transmit_receive(s_dev, &reg, 1, b, 6, 50);
    if (err == ESP_OK) {
        for (int a = 0; a < 3; a++) {
            raw[a] = (int16_t)(b[2 * a] | b[2 * a + 1] << 8);
        }
    }
    return err;
}
