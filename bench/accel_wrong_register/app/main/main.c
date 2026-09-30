/* Tilt meter: reads an ADXL345 (I2C0, SDA 21 / SCL 22, address 0x53) and prints the tilt from
 * vertical, in degrees, every 200 ms. */
#include <math.h>
#include <stdio.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define ADXL345_ADDR    0x53
#define REG_DEVID       0x00
#define REG_POWER_CTL   0x2D
#define REG_DATA_FORMAT 0x31
#define REG_DATA        0x33

static i2c_master_dev_handle_t s_dev;

static void reg_write(uint8_t reg, uint8_t val)
{
    uint8_t b[2] = {reg, val};
    ESP_ERROR_CHECK(i2c_master_transmit(s_dev, b, 2, 100));
}

static void reg_read(uint8_t reg, uint8_t *out, size_t n)
{
    ESP_ERROR_CHECK(i2c_master_transmit_receive(s_dev, &reg, 1, out, n, 100));
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
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = ADXL345_ADDR, .scl_speed_hz = 400000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &s_dev));

    uint8_t id;
    reg_read(REG_DEVID, &id, 1);
    printf("accelerometer id 0x%02x\n", id);
    reg_write(REG_DATA_FORMAT, 0x08);   /* full resolution, +-2 g: 256 LSB/g */
    reg_write(REG_POWER_CTL, 0x08);     /* measure */

    for (;;) {
        uint8_t raw[6];
        reg_read(REG_DATA, raw, sizeof(raw));
        float x = (int16_t)(raw[0] | raw[1] << 8) / 256.0f;
        float y = (int16_t)(raw[2] | raw[3] << 8) / 256.0f;
        float z = (int16_t)(raw[4] | raw[5] << 8) / 256.0f;
        float tilt = atan2f(sqrtf(x * x + y * y), z) * 180.0f / (float)M_PI;
        printf("tilt=%.1f deg\n", tilt);
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}
