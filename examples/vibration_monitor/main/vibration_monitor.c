/*
 * vibration_monitor: reads an ADXL345 accelerometer over I2C at 400 Hz and prints the AC RMS of
 * each axis per block of 256 samples (0.64 s). In esp32-sim-mcp the ADXL345 is emulated and fed a
 * synthetic or recorded waveform, so the printed RMS can be checked against the injected signal.
 */
#include <math.h>
#include <stdio.h>
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define ADXL345_ADDR        0x53
#define REG_DEVID           0x00
#define REG_BW_RATE         0x2C
#define REG_POWER_CTL       0x2D
#define REG_DATA_FORMAT     0x31
#define REG_DATAX0          0x32

#define SAMPLE_PERIOD_US    2500    /* 400 Hz */
#define BLOCK               256
#define G_PER_LSB           0.0039f /* full resolution: 3.9 mg/LSB at any range */

static i2c_master_dev_handle_t s_dev;
static TaskHandle_t s_task;

static esp_err_t reg_write(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};
    return i2c_master_transmit(s_dev, buf, sizeof(buf), 100);
}

static esp_err_t reg_read(uint8_t reg, uint8_t *out, size_t n)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, out, n, 100);
}

static void on_sample_timer(void *arg)
{
    xTaskNotifyGive(s_task);
}

static void sampler(void *arg)
{
    float sum[3] = {0}, sum_sq[3] = {0};
    int n = 0, block = 0;

    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        uint8_t raw[6];
        if (reg_read(REG_DATAX0, raw, sizeof(raw)) != ESP_OK) {
            printf("read error\n");
            continue;
        }
        for (int axis = 0; axis < 3; axis++) {
            float g = (int16_t)(raw[2 * axis] | raw[2 * axis + 1] << 8) * G_PER_LSB;
            sum[axis] += g;
            sum_sq[axis] += g * g;
        }
        if (++n == BLOCK) {
            float rms[3], mean[3];
            for (int axis = 0; axis < 3; axis++) {
                mean[axis] = sum[axis] / BLOCK;
                float var = sum_sq[axis] / BLOCK - mean[axis] * mean[axis];
                rms[axis] = sqrtf(var > 0 ? var : 0);   /* AC RMS: DC (gravity) removed */
                sum[axis] = sum_sq[axis] = 0;
            }
            printf("block %d rms_x=%.4f rms_y=%.4f rms_z=%.4f mean_z=%.3f\n",
                   ++block, rms[0], rms[1], rms[2], mean[2]);
            n = 0;
        }
    }
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
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = ADXL345_ADDR,
        .scl_speed_hz = 400000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &s_dev));

    uint8_t id = 0;
    ESP_ERROR_CHECK(reg_read(REG_DEVID, &id, 1));
    printf("ADXL345 DEVID=0x%02x\n", id);
    if (id != 0xE5) {
        printf("unexpected device, stopping\n");
        return;
    }
    ESP_ERROR_CHECK(reg_write(REG_DATA_FORMAT, 0x09));  /* FULL_RES, +-4 g */
    ESP_ERROR_CHECK(reg_write(REG_BW_RATE, 0x0C));      /* 400 Hz output data rate */
    ESP_ERROR_CHECK(reg_write(REG_POWER_CTL, 0x08));    /* measure */

    xTaskCreatePinnedToCore(sampler, "sampler", 4096, NULL, 10, &s_task, 1);
    const esp_timer_create_args_t targs = {.callback = on_sample_timer, .name = "sample"};
    esp_timer_handle_t timer;
    ESP_ERROR_CHECK(esp_timer_create(&targs, &timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(timer, SAMPLE_PERIOD_US));
    printf("sampling at %d Hz, block of %d\n", 1000000 / SAMPLE_PERIOD_US, BLOCK);
}
