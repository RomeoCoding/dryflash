/*
 * verus_pod: a Verus-style sensor pod in ESP-IDF, written to run unchanged on the board and in
 * dryflash. Wiring (Verus-Wiring-Map, 2026-10-03): ESP32 DevKit; I2C0 SDA 21 / SCL 22 with an
 * MPU-6050 (0x68), an ADS1115 (CONFIG_VERUS_ADS1115_ADDR; 0x48 on the board, 0x49 in dryflash,
 * whose emulated machine has a TMP105 at 0x48) reading an SS49E Hall sensor on AIN0, and an
 * SSD1306 OLED (0x3C); a MAX31855 on VSPI (SCK 18, MISO 19, CS 5); a pairing button on GPIO27
 * to GND (pull-up); a status LED on GPIO25.
 *
 * Output on UART0 is newline-delimited JSON only (the Verus wire format, phase 5):
 *   {"type":"features","features":{...},"active_modules":[...],"ts":ms}   every 500 ms
 *   {"type":"module","event":"attached"|"detached","id":...,"module_type":...,"ts":ms}
 *   {"type":"log","event":"pairing","code":"123456","window_s":60,"ts":ms}
 */
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/spi_master.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "oled.h"

#define PIN_SDA         21
#define PIN_SCL         22
#define PIN_SCK         18
#define PIN_MISO        19
#define PIN_TC_CS       5
#define PIN_BUTTON      27
#define PIN_LED         25
#define MPU_ADDR        0x68
#define OLED_ADDR       0x3C

#define VIB_PERIOD_US   2000        /* MPU-6050 at 500 Hz (DLPF on, SMPLRT_DIV 1) */
#define HALL_PERIOD_US  1163        /* ADS1115 at its 860 SPS */
#define HALL_WINDOW     172         /* 200 ms = 10 cycles of 50 Hz mains at 860 SPS */
#define FEATURE_MS      500
#define PAIRING_S       60

#define ID_VIB  "vib_mpu6050_0x68"
#define ID_CUR  "cur_ss49e_ads0"
#define ID_TMP  "tmp_max31855_cs5"

static i2c_master_dev_handle_t s_mpu, s_ads;
static spi_device_handle_t s_tc;
static TaskHandle_t s_vib_task, s_hall_task, s_pair_task;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

/* Vibration: sums over the current 500 ms window, per axis (g) */
static double s_vsum[3], s_vsq[3];
static int s_vn;
/* Hall: ring of the last HALL_WINDOW conversions (volts) */
static float s_hall[HALL_WINDOW];
static int s_hall_pos, s_hall_count;

static bool s_have_vib, s_have_cur, s_have_tmp;

static long now_ms(void)
{
    return (long)(esp_timer_get_time() / 1000);
}

static esp_err_t reg_write(i2c_master_dev_handle_t dev, uint8_t reg, const uint8_t *val, size_t n)
{
    uint8_t buf[4] = {reg};
    memcpy(buf + 1, val, n);
    return i2c_master_transmit(dev, buf, n + 1, 50);
}

static esp_err_t reg_read(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t *out, size_t n)
{
    return i2c_master_transmit_receive(dev, &reg, 1, out, n, 50);
}

static void notify_task(void *arg)
{
    xTaskNotifyGive((TaskHandle_t)arg);
}

/* ----- MPU-6050: acceleration at 500 Hz, +-2 g (16384 LSB/g) ---------------------------------- */
static void vib_task(void *arg)
{
    for (;;) {
        uint8_t b[6];
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        if (reg_read(s_mpu, 0x3B, b, sizeof(b)) != ESP_OK) {
            continue;
        }
        taskENTER_CRITICAL(&s_lock);
        for (int i = 0; i < 3; i++) {
            double g = (int16_t)(b[2 * i] << 8 | b[2 * i + 1]) / 16384.0;
            s_vsum[i] += g;
            s_vsq[i] += g * g;
        }
        s_vn++;
        taskEXIT_CRITICAL(&s_lock);
    }
}

/* RMS of the acceleration vector after removing each axis' mean over the window */
static float vib_rms_take(void)
{
    double var = 0;
    taskENTER_CRITICAL(&s_lock);
    int n = s_vn;
    for (int i = 0; i < 3 && n > 0; i++) {
        double m = s_vsum[i] / n;
        var += s_vsq[i] / n - m * m;
    }
    memset(s_vsum, 0, sizeof(s_vsum));
    memset(s_vsq, 0, sizeof(s_vsq));
    s_vn = 0;
    taskEXIT_CRITICAL(&s_lock);
    return n > 0 ? sqrtf(var > 0 ? var : 0) : 0;
}

/* ----- ADS1115: AIN0 continuous at 860 SPS, +-2.048 V (62.5 uV/LSB) ---------------------------- */
static void hall_task(void *arg)
{
    for (;;) {
        uint8_t b[2];
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        if (reg_read(s_ads, 0x00, b, sizeof(b)) != ESP_OK) {
            continue;
        }
        float v = (int16_t)(b[0] << 8 | b[1]) * (2.048f / 32768.0f);
        taskENTER_CRITICAL(&s_lock);
        s_hall[s_hall_pos] = v;
        s_hall_pos = (s_hall_pos + 1) % HALL_WINDOW;
        if (s_hall_count < HALL_WINDOW) {
            s_hall_count++;
        }
        taskEXIT_CRITICAL(&s_lock);
    }
}

/* AC RMS in mV over the last 10 mains cycles: the DC offset (SS49E mid-rail) is removed */
static float hall_ac_mv(void)
{
    float w[HALL_WINDOW];
    int n;
    taskENTER_CRITICAL(&s_lock);
    n = s_hall_count;
    memcpy(w, s_hall, sizeof(w));
    taskEXIT_CRITICAL(&s_lock);
    if (n < HALL_WINDOW) {
        return 0;
    }
    double mean = 0, sq = 0;
    for (int i = 0; i < n; i++) {
        mean += w[i];
    }
    mean /= n;
    for (int i = 0; i < n; i++) {
        sq += (w[i] - mean) * (w[i] - mean);
    }
    return sqrtf(sq / n) * 1000.0f;
}

/* ----- MAX31855: 32-bit frame, polling transfer without DMA ------------------------------------ */
static bool tc_read(float *temp_c)
{
    spi_transaction_t t = {.flags = SPI_TRANS_USE_RXDATA, .length = 32};
    if (spi_device_polling_transmit(s_tc, &t) != ESP_OK) {
        return false;
    }
    uint32_t w = (uint32_t)t.rx_data[0] << 24 | t.rx_data[1] << 16 | t.rx_data[2] << 8 | t.rx_data[3];
    if (w & 0x10000) {  /* D16: OC, SCG or SCV fault */
        return false;
    }
    *temp_c = ((int32_t)w >> 18) * 0.25f;
    return true;
}

static void module_event(const char *event, const char *id, const char *type)
{
    printf("{\"type\":\"module\",\"event\":\"%s\",\"id\":\"%s\",\"module_type\":\"%s\",\"ts\":%ld}\n",
           event, id, type, now_ms());
}

/* ----- pairing: button -> 60 s window, random code on the OLED, LED blinking ------------------- */
static int64_t s_last_press_us;

static void IRAM_ATTR on_button(void *arg)
{
    int64_t t = esp_timer_get_time();
    if (t - s_last_press_us > 50000) {  /* software debounce, 50 ms */
        s_last_press_us = t;
        BaseType_t woken = pdFALSE;
        vTaskNotifyGiveFromISR(s_pair_task, &woken);
        portYIELD_FROM_ISR(woken);
    }
}

static void show_idle(void)
{
    oled_clear();
    oled_text(34, 24, 2, "VERUS");
    oled_flush();
}

static void pair_task(void *arg)
{
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        char code[8];
        snprintf(code, sizeof(code), "%06lu", (unsigned long)(esp_random() % 1000000));
        printf("{\"type\":\"log\",\"event\":\"pairing\",\"code\":\"%s\",\"window_s\":%d,\"ts\":%ld}\n",
               code, PAIRING_S, now_ms());
        oled_clear();
        oled_text(40, 2, 2, "PAIR");
        oled_text(10, 30, 3, code);
        oled_flush();
        int64_t end = esp_timer_get_time() + PAIRING_S * 1000000LL;
        int level = 0;
        while (esp_timer_get_time() < end) {
            level = !level;
            gpio_set_level(PIN_LED, level);
            vTaskDelay(pdMS_TO_TICKS(250));  /* 2 Hz blink */
        }
        gpio_set_level(PIN_LED, 0);
        ulTaskNotifyTake(pdTRUE, 0);         /* presses during the window do not queue another */
        show_idle();
    }
}

/* ----- setup --------------------------------------------------------------------------------- */
static void start_periodic(const char *name, TaskHandle_t task, uint64_t period_us)
{
    const esp_timer_create_args_t args = {.callback = notify_task, .arg = task, .name = name};
    esp_timer_handle_t h;
    ESP_ERROR_CHECK(esp_timer_create(&args, &h));
    ESP_ERROR_CHECK(esp_timer_start_periodic(h, period_us));
}

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0, .sda_io_num = PIN_SDA, .scl_io_num = PIN_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7, .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    i2c_device_config_t mpu = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = MPU_ADDR,
                               .scl_speed_hz = 400000};
    i2c_device_config_t ads = {.dev_addr_length = I2C_ADDR_BIT_LEN_7,
                               .device_address = CONFIG_VERUS_ADS1115_ADDR, .scl_speed_hz = 400000};
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &mpu, &s_mpu));
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &ads, &s_ads));

    uint8_t who = 0;
    if (reg_read(s_mpu, 0x75, &who, 1) == ESP_OK && who == 0x68) {
        static const uint8_t wake = 0x01, div = 1, dlpf = 3, afs = 0;
        reg_write(s_mpu, 0x6B, &wake, 1);   /* leave sleep, PLL with X gyro */
        reg_write(s_mpu, 0x19, &div, 1);    /* 1 kHz / (1 + 1) = 500 Hz */
        reg_write(s_mpu, 0x1A, &dlpf, 1);
        reg_write(s_mpu, 0x1C, &afs, 1);    /* +-2 g */
        s_have_vib = true;
    }
    /* MUX 100 (AIN0-GND), PGA 010 (+-2.048 V), continuous, 860 SPS, comparator off */
    static const uint8_t ads_cfg[2] = {0x44, 0xE3};
    s_have_cur = reg_write(s_ads, 0x01, ads_cfg, 2) == ESP_OK;

    spi_bus_config_t spi = {.mosi_io_num = -1, .miso_io_num = PIN_MISO, .sclk_io_num = PIN_SCK,
                            .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 4};
    spi_device_interface_config_t tc = {.clock_speed_hz = 4000000, .mode = 0, .spics_io_num = PIN_TC_CS,
                                        .queue_size = 1};
    ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &spi, SPI_DMA_DISABLED));  /* DMA: not emulated */
    ESP_ERROR_CHECK(spi_bus_add_device(SPI3_HOST, &tc, &s_tc));

    gpio_config_t led = {.pin_bit_mask = 1ULL << PIN_LED, .mode = GPIO_MODE_OUTPUT};
    gpio_config_t btn = {.pin_bit_mask = 1ULL << PIN_BUTTON, .mode = GPIO_MODE_INPUT,
                         .pull_up_en = GPIO_PULLUP_ENABLE, .intr_type = GPIO_INTR_NEGEDGE};
    ESP_ERROR_CHECK(gpio_config(&led));
    ESP_ERROR_CHECK(gpio_config(&btn));
    gpio_set_level(PIN_LED, 0);

    if (oled_init(bus, OLED_ADDR) == ESP_OK) {
        show_idle();
    }

    xTaskCreate(vib_task, "vib", 3072, NULL, 6, &s_vib_task);
    xTaskCreate(hall_task, "hall", 3072, NULL, 6, &s_hall_task);
    xTaskCreate(pair_task, "pair", 3072, NULL, 4, &s_pair_task);
    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(PIN_BUTTON, on_button, NULL));
    if (s_have_vib) {
        module_event("attached", ID_VIB, "vibration");
        start_periodic("vib", s_vib_task, VIB_PERIOD_US);
    }
    if (s_have_cur) {
        module_event("attached", ID_CUR, "current");
        start_periodic("hall", s_hall_task, HALL_PERIOD_US);
    }

    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(FEATURE_MS));
        float temp = 0;
        bool tmp_ok = tc_read(&temp);
        if (tmp_ok != s_have_tmp) {  /* the open-circuit fault is the probe's hot-plug signal */
            s_have_tmp = tmp_ok;
            module_event(tmp_ok ? "attached" : "detached", ID_TMP, "temperature");
        }
        char feat[160] = "", mods[96] = "";
        int fl = 0, ml = 0;
        if (s_have_vib) {
            fl += snprintf(feat + fl, sizeof(feat) - fl, "%s\"vib_rms_g\":%.4f", fl ? "," : "", vib_rms_take());
        }
        if (s_have_cur) {
            fl += snprintf(feat + fl, sizeof(feat) - fl, "%s\"hall_ac_mv\":%.2f", fl ? "," : "", hall_ac_mv());
            ml += snprintf(mods + ml, sizeof(mods) - ml, "%s\"" ID_CUR "\"", ml ? "," : "");
        }
        if (s_have_tmp) {
            fl += snprintf(feat + fl, sizeof(feat) - fl, "%s\"temp_c\":%.2f", fl ? "," : "", temp);
            ml += snprintf(mods + ml, sizeof(mods) - ml, "%s\"" ID_TMP "\"", ml ? "," : "");
        }
        if (s_have_vib) {
            ml += snprintf(mods + ml, sizeof(mods) - ml, "%s\"" ID_VIB "\"", ml ? "," : "");
        }
        printf("{\"type\":\"features\",\"features\":{%s},\"active_modules\":[%s],\"ts\":%ld}\n", feat, mods,
               now_ms());
    }
}
