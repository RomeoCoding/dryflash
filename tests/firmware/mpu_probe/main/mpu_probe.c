/*
 * mpu_probe: MPU-6050 driver exercise for the sensor-injection tests. Identity and power-on
 * registers, reads while asleep (zeros), a DEVICE_RESET polled until it clears (as Adafruit's
 * driver does), wake-up, and a burst read of all 14 data bytes at each accelerometer and gyro
 * range (bank selection over several register fields), then one line every 100 ms.
 */
#include <stdio.h>
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define MPU_ADDR      0x68
#define SMPLRT_DIV    0x19
#define GYRO_CONFIG   0x1B
#define ACCEL_CONFIG  0x1C
#define INT_STATUS    0x3A
#define ACCEL_XOUT_H  0x3B
#define PWR_MGMT_1    0x6B
#define WHO_AM_I      0x75

static i2c_master_dev_handle_t s_dev;

static uint8_t rd(uint8_t reg)
{
    uint8_t v = 0;
    ESP_ERROR_CHECK(i2c_master_transmit_receive(s_dev, &reg, 1, &v, 1, 100));
    return v;
}

static void wr(uint8_t reg, uint8_t v)
{
    uint8_t b[2] = {reg, v};
    ESP_ERROR_CHECK(i2c_master_transmit(s_dev, b, 2, 100));
}

/* a[0..2] accel, a[3] temp, a[4..6] gyro: raw big-endian int16 */
static void burst(int16_t a[7])
{
    uint8_t reg = ACCEL_XOUT_H, b[14];
    ESP_ERROR_CHECK(i2c_master_transmit_receive(s_dev, &reg, 1, b, sizeof(b), 100));
    for (int i = 0; i < 7; i++) {
        a[i] = (int16_t)(b[2 * i] << 8 | b[2 * i + 1]);
    }
}

static void report(const char *tag, int afs, int fs)
{
    static const float g_lsb[4] = {16384, 8192, 4096, 2048};
    static const float dps_lsb[4] = {131, 65.5f, 32.8f, 16.4f};
    int16_t a[7];

    burst(a);
    printf("%s afs%d fs%d raw=%d,%d,%d,%d,%d,%d,%d g=%.4f,%.4f,%.4f t=%.2f dps=%.2f,%.2f,%.2f\n",
           tag, afs, fs, a[0], a[1], a[2], a[3], a[4], a[5], a[6],
           a[0] / g_lsb[afs], a[1] / g_lsb[afs], a[2] / g_lsb[afs], a[3] / 340.0f + 36.53f,
           a[4] / dps_lsb[fs], a[5] / dps_lsb[fs], a[6] / dps_lsb[fs]);
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
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = MPU_ADDR, .scl_speed_hz = 400000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &s_dev));

    printf("who_am_i 0x%02x pwr_mgmt_1 0x%02x\n", rd(WHO_AM_I), rd(PWR_MGMT_1));
    vTaskDelay(pdMS_TO_TICKS(20));
    report("asleep", 0, 0);

    wr(PWR_MGMT_1, rd(PWR_MGMT_1) | 0x80);  /* DEVICE_RESET, then poll like Adafruit_MPU6050 */
    int polls = 0;
    while ((rd(PWR_MGMT_1) & 0x80) && polls < 100) {
        polls++;
        vTaskDelay(1);
    }
    printf("reset bit clear after %d polls, pwr_mgmt_1 0x%02x\n", polls, rd(PWR_MGMT_1));

    wr(PWR_MGMT_1, 0x01);                   /* wake, PLL with X gyro reference */
    wr(SMPLRT_DIV, 9);
    printf("awake pwr_mgmt_1 0x%02x int_status 0x%02x\n", rd(PWR_MGMT_1), rd(INT_STATUS));
    for (int afs = 0; afs < 4; afs++) {
        for (int fs = 0; fs < 4; fs++) {
            wr(ACCEL_CONFIG, afs << 3);
            wr(GYRO_CONFIG, fs << 3);
            report("range", afs, fs);
        }
    }
    wr(ACCEL_CONFIG, 1 << 3);
    wr(GYRO_CONFIG, 1 << 3);
    for (int tick = 0;; tick++) {
        vTaskDelay(pdMS_TO_TICKS(100));
        char tag[16];
        snprintf(tag, sizeof(tag), "tick %d", tick);
        report(tag, 1, 1);
    }
}
