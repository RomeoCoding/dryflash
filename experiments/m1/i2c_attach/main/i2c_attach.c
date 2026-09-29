/*
 * M1 question 2 follow-up: with patch 0001, tmp105 devices attached from the command line
 * (-device tmp105,bus=i2c-bus.N,address=A,temperature=T) must be readable from firmware.
 */
#include <stdio.h>
#include "driver/i2c_master.h"

static void read_temp(i2c_master_bus_handle_t bus, int port, uint16_t addr)
{
    i2c_device_config_t cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = addr, .scl_speed_hz = 100000 };
    i2c_master_dev_handle_t dev;
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &cfg, &dev));
    uint8_t reg = 0, rx[2] = {0};
    esp_err_t err = i2c_master_transmit_receive(dev, &reg, 1, rx, 2, 100);
    printf("port %d addr 0x%02x: %s raw=%02x%02x temp=%.2f C\n", port, addr, esp_err_to_name(err), rx[0], rx[1],
           (int16_t)((rx[0] << 8) | rx[1]) / 256.0);
}

void app_main(void)
{
    i2c_master_bus_handle_t bus0, bus1;
    i2c_master_bus_config_t c0 = { .i2c_port = 0, .sda_io_num = 21, .scl_io_num = 22, .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7 };
    i2c_master_bus_config_t c1 = { .i2c_port = 1, .sda_io_num = 18, .scl_io_num = 19, .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7 };
    ESP_ERROR_CHECK(i2c_new_master_bus(&c0, &bus0));
    ESP_ERROR_CHECK(i2c_new_master_bus(&c1, &bus1));
    read_temp(bus0, 0, 0x48);   /* hard-wired by the machine, 25 C */
    read_temp(bus0, 0, 0x49);   /* -device on i2c-bus.0 */
    read_temp(bus1, 1, 0x4a);   /* -device on i2c-bus.1 */
    printf("probe port1 0x48 (must be absent): %s\n", esp_err_to_name(i2c_master_probe(bus1, 0x48, 100)));
    printf("I2C_ATTACH_DONE\n");
}
