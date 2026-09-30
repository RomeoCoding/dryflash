/* Shock detector: an ADXL345 (I2C0, SDA 21 / SCL 22, address 0x53) configured for +-8 g. Prints
 * the Z acceleration every 100 ms and "ALARM: shock" when any axis exceeds 2 g. */
#include <math.h>
#include <stdio.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define ADXL345_ADDR    0x53
#define REG_POWER_CTL   0x2D
#define REG_DATA_FORMAT 0x31
#define REG_DATAX0      0x32
#define SHOCK_G         2.0f
#define G_PER_LSB       0.0039f

static i2c_master_dev_handle_t s_dev;

static void reg_write(uint8_t reg, uint8_t val)
{
    uint8_t b[2] = {reg, val};
    ESP_ERROR_CHECK(i2c_master_transmit(s_dev, b, 2, 100));
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
    reg_write(REG_DATA_FORMAT, 0x02);   /* +-8 g range */
    reg_write(REG_POWER_CTL, 0x08);     /* measure */
    printf("shock detector armed (threshold %.1f g)\n", SHOCK_G);

    for (int n = 0;; n++) {
        uint8_t reg = REG_DATAX0, raw[6];
        ESP_ERROR_CHECK(i2c_master_transmit_receive(s_dev, &reg, 1, raw, 6, 100));
        float g[3];
        for (int a = 0; a < 3; a++) {
            g[a] = (int16_t)(raw[2 * a] | raw[2 * a + 1] << 8) * G_PER_LSB;
        }
        if (fabsf(g[0]) > SHOCK_G || fabsf(g[1]) > SHOCK_G || fabsf(g[2]) > SHOCK_G) {
            printf("ALARM: shock x=%.2f y=%.2f z=%.2f g\n", g[0], g[1], g[2]);
        }
        if (n % 5 == 0) {
            printf("z=%.2f g\n", g[2]);
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
