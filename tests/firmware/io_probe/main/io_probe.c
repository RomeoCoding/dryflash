/*
 * io_probe: GPIO and SPI exercise for the M5 integration tests.
 *  - LED on GPIO25 toggled every 250 ms (2 Hz blink).
 *  - Button on GPIO27 (input, pull-up configured, falling-edge interrupt): each press is printed
 *    with the level read back.
 *  - MAX31855 on SPI3 (VSPI: SCK 18, MISO 19, CS 5 through the controller), ESP-IDF spi_master
 *    without DMA: one polling and one interrupt-driven read every 500 ms.
 *  - MAX6675 on SPI2 (HSPI: SCK 14, MISO 12) read the way Arduino-ESP32 and Adafruit drivers do:
 *    controller CS left enabled, chip select toggled by hand on GPIO15.
 */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_timer.h"
#include "soc/spi_struct.h"

#define LED_GPIO     25
#define BUTTON_GPIO  27
#define TC_CS_GPIO   5
#define K_CS_GPIO    15

static QueueHandle_t s_presses;
static spi_device_handle_t s_tc;

static void IRAM_ATTR on_button(void *arg)
{
    int64_t t = esp_timer_get_time();
    xQueueSendFromISR(s_presses, &t, NULL);
}

static void blink_task(void *arg)
{
    int level = 0;
    for (;;) {
        level = !level;
        gpio_set_level(LED_GPIO, level);
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}

static void print_max31855(const char *how, const uint8_t *rx)
{
    uint32_t w = (uint32_t)rx[0] << 24 | rx[1] << 16 | rx[2] << 8 | rx[3];
    int32_t tc = (int32_t)w >> 18;               /* 14-bit signed, 0.25 degC */
    int32_t cj = (int32_t)(w << 16) >> 20;       /* 12-bit signed, 0.0625 degC */
    printf("max31855 %s raw=0x%08" PRIx32 " tc=%.2f cj=%.4f fault=%d oc=%d scg=%d scv=%d\n", how, w,
           tc * 0.25, cj * 0.0625, (int)(w >> 16 & 1), (int)(w & 1), (int)(w >> 1 & 1), (int)(w >> 2 & 1));
}

static void read_max31855(void)
{
    spi_transaction_t t = {.flags = SPI_TRANS_USE_RXDATA, .length = 32};
    spi_transaction_t *done;

    ESP_ERROR_CHECK(spi_device_polling_transmit(s_tc, &t));
    print_max31855("polling", t.rx_data);
    memset(&t, 0, sizeof(t));
    t.flags = SPI_TRANS_USE_RXDATA;
    t.length = 32;
    ESP_ERROR_CHECK(spi_device_queue_trans(s_tc, &t, portMAX_DELAY));
    esp_err_t err = spi_device_get_trans_result(s_tc, &done, pdMS_TO_TICKS(200));
    if (err == ESP_OK) {
        print_max31855("interrupt", t.rx_data);
    } else {
        printf("max31855 interrupt %s\n", esp_err_to_name(err));
    }
}

/* Arduino-ESP32 3.3.12 spiInitBus + spiStartBus user bits, then spiTransferBytesNL */
static void hspi_init_arduino_style(void)
{
    SPI2.slave.val = 0;
    SPI2.pin.val = 0;            /* CS0..2 enabled in the controller, routed nowhere */
    SPI2.user.val = 0;
    SPI2.user1.val = 0;
    SPI2.ctrl.val = 0;
    SPI2.ctrl1.val = 0;
    SPI2.ctrl2.val = 0;
    SPI2.user.usr_mosi = 1;
    SPI2.user.usr_miso = 1;
    SPI2.user.doutdin = 1;
}

static void read_max6675_arduino_style(void)
{
    uint32_t w;

    gpio_set_level(K_CS_GPIO, 0);
    SPI2.mosi_dlen.usr_mosi_dbitlen = 15;
    SPI2.miso_dlen.usr_miso_dbitlen = 15;
    SPI2.data_buf[0] = 0xffffffff;   /* Adafruit read(): 0xFF filler */
    SPI2.cmd.usr = 1;
    while (SPI2.cmd.usr) {
    }
    w = SPI2.data_buf[0];
    gpio_set_level(K_CS_GPIO, 1);
    uint16_t v = (uint16_t)((w & 0xff) << 8 | (w >> 8 & 0xff));
    printf("max6675 raw=0x%04x tc=%.2f open=%d\n", v, (v >> 3) * 0.25, (v >> 2) & 1);
}

void app_main(void)
{
    gpio_config_t led = {.pin_bit_mask = 1ULL << LED_GPIO, .mode = GPIO_MODE_INPUT_OUTPUT};
    gpio_config_t btn = {.pin_bit_mask = 1ULL << BUTTON_GPIO, .mode = GPIO_MODE_INPUT,
                         .pull_up_en = GPIO_PULLUP_ENABLE, .intr_type = GPIO_INTR_NEGEDGE};
    gpio_config_t kcs = {.pin_bit_mask = 1ULL << K_CS_GPIO, .mode = GPIO_MODE_OUTPUT};
    spi_bus_config_t bus = {.mosi_io_num = 23, .miso_io_num = 19, .sclk_io_num = 18,
                            .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 64};
    spi_device_interface_config_t dev = {.clock_speed_hz = 1000000, .mode = 0,
                                         .spics_io_num = TC_CS_GPIO, .queue_size = 1};

    ESP_ERROR_CHECK(gpio_config(&led));
    ESP_ERROR_CHECK(gpio_config(&btn));
    ESP_ERROR_CHECK(gpio_config(&kcs));
    gpio_set_level(K_CS_GPIO, 1);
    s_presses = xQueueCreate(8, sizeof(int64_t));
    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(BUTTON_GPIO, on_button, NULL));
    ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_DISABLED));
    ESP_ERROR_CHECK(spi_bus_add_device(SPI3_HOST, &dev, &s_tc));
    hspi_init_arduino_style();
    printf("io_probe ready, button level %d\n", gpio_get_level(BUTTON_GPIO));
    xTaskCreate(blink_task, "blink", 2048, NULL, 5, NULL);

    int64_t next = esp_timer_get_time();
    for (;;) {
        int64_t t;
        if (xQueueReceive(s_presses, &t, pdMS_TO_TICKS(10))) {
            printf("button pressed at %" PRId64 " ms, level %d\n", t / 1000, gpio_get_level(BUTTON_GPIO));
        }
        if (esp_timer_get_time() >= next) {
            next += 500000;
            read_max31855();
            read_max6675_arduino_style();
        }
    }
}
