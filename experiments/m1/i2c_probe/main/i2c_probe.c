/*
 * M1 question 3: does the ESP-IDF v6.1 i2c_master driver complete register
 * transactions through QEMU's esp32_i2c.c? Talks to the tmp105 that the esp32
 * machine hard-wires at 0x48 on I2C0 (25.0 C => temp register 0x19 0x00).
 */
#include <stdio.h>
#include <inttypes.h>
#include "driver/i2c_master.h"
#include "esp_err.h"

#define ADDR_TMP105 0x48

static void report(const char *what, esp_err_t err, const uint8_t *buf, size_t n)
{
    printf("%s: %s", what, esp_err_to_name(err));
    for (size_t i = 0; i < n; i++) {
        printf(" %02x", buf[i]);
    }
    printf("\n");
}

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0,
        .sda_io_num = 21,
        .scl_io_num = 22,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

    esp_err_t err = i2c_master_probe(bus, ADDR_TMP105, 100);
    printf("probe 0x48: %s\n", esp_err_to_name(err));
    err = i2c_master_probe(bus, 0x50, 100);
    printf("probe 0x50 (absent): %s\n", esp_err_to_name(err));

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = ADDR_TMP105,
        .scl_speed_hz = 100000,
    };
    i2c_master_dev_handle_t dev;
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &dev));

    uint8_t reg = 0x00;
    uint8_t rx[2] = {0};
    err = i2c_master_transmit_receive(dev, &reg, 1, rx, 2, 100);
    report("read temp (reg 0x00)", err, rx, 2);

    /* Write config register (0x01) then read it back: exercises write + repeated start. */
    uint8_t wr[2] = {0x01, 0x60};
    err = i2c_master_transmit(dev, wr, 2, 100);
    report("write config 0x60", err, wr, 2);
    reg = 0x01;
    rx[0] = 0;
    err = i2c_master_transmit_receive(dev, &reg, 1, rx, 1, 100);
    report("read config (reg 0x01)", err, rx, 1);

    /* Long read (> 1 FIFO worth is not possible on tmp105, but 40 bytes forces END-chunking). */
    uint8_t big[40] = {0};
    reg = 0x00;
    err = i2c_master_transmit_receive(dev, &reg, 1, big, sizeof(big), 100);
    report("read 40 bytes", err, big, 4);

    printf("I2C_PROBE_DONE\n");
}
