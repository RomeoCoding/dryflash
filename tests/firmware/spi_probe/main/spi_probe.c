/*
 * M5 step-0 probe: how far do SPI2/SPI3 and GPIO get in Espressif's QEMU?
 *
 * Run with a test SSI device on SPI3 CS0 and SPI2 CS0. Every section prints what it
 * received, so the UART log plus the device-side trace answers:
 *   B  an Arduino-ESP32-style register sequence (CS by GPIO, controller CS left enabled);
 *   A  ESP-IDF spi_master without DMA: polling and interrupt-driven transfers;
 *   C  ESP-IDF spi_master with DMA;
 *   D  GPIO output, input and interrupt registration;
 *   E  NVS and raw flash through SPI1 (a regression check for SPI controller changes).
 */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "soc/spi_struct.h"
#include "soc/gpio_reg.h"
#include "soc/soc.h"
#include "nvs_flash.h"
#include "esp_partition.h"

static void dump(const char *what, const uint8_t *b, int n)
{
    printf("%s:", what);
    for (int i = 0; i < n; i++) {
        printf(" %02x", b[i]);
    }
    printf("\n");
}

/* Arduino-ESP32 3.3.12 esp32-hal-spi.c: spiInitBus() then spiStartBus() user bits */
static void arduino_init_bus(spi_dev_t *dev)
{
    dev->slave.trans_done = 0;
    dev->slave.val = 0;
    dev->pin.val = 0;          /* CS0..CS2 enabled in the controller, routed nowhere */
    dev->user.val = 0;
    dev->user1.val = 0;
    dev->ctrl.val = 0;
    dev->ctrl1.val = 0;
    dev->ctrl2.val = 0;
    dev->clock.val = 0;
    dev->user.usr_mosi = 1;
    dev->user.usr_miso = 1;
    dev->user.doutdin = 1;
}

/* Arduino-ESP32 3.3.12 spiTransferBytesNL() for len <= 64 */
static void arduino_transfer(spi_dev_t *dev, uint8_t *buf, int len)
{
    uint32_t w[16];

    memcpy(w, buf, len);
    dev->mosi_dlen.usr_mosi_dbitlen = len * 8 - 1;
    dev->miso_dlen.usr_miso_dbitlen = len * 8 - 1;
    for (int i = 0; i < (len + 3) / 4; i++) {
        dev->data_buf[i] = w[i];
    }
    dev->cmd.usr = 1;
    while (dev->cmd.usr) {
    }
    for (int i = 0; i < (len + 3) / 4; i++) {
        w[i] = dev->data_buf[i];
    }
    memcpy(buf, w, len);
}

static void section_b_arduino(void)
{
    uint8_t buf[4];

    printf("B: Arduino-style on SPI3, CS = GPIO5 via gpio_set_level\n");
    gpio_reset_pin(5);
    gpio_set_direction(5, GPIO_MODE_OUTPUT);
    gpio_set_level(5, 1);
    arduino_init_bus(&SPI3);

    /* Adafruit_MAX31855::spiread32 -> Adafruit_SPIDevice::read(buf, 4), sendvalue 0xFF */
    memset(buf, 0xff, sizeof(buf));
    gpio_set_level(5, 0);
    arduino_transfer(&SPI3, buf, 4);
    gpio_set_level(5, 1);
    dump("B1 read(4) with 0xFF filler", buf, 4);

    memset(buf, 0x00, sizeof(buf));
    gpio_set_level(5, 0);
    arduino_transfer(&SPI3, buf, 4);
    gpio_set_level(5, 1);
    dump("B2 read(4) with 0x00 filler", buf, 4);

    /* two transfers inside one GPIO-CS window, as write_then_read() does */
    memset(buf, 0x00, sizeof(buf));
    gpio_set_level(5, 0);
    arduino_transfer(&SPI3, buf, 1);
    arduino_transfer(&SPI3, buf + 1, 3);
    gpio_set_level(5, 1);
    dump("B3 1+3 bytes in one CS window (device should give de ad be ef)", buf, 4);
    printf("B: SPI3 pin reg = 0x%08" PRIx32 "\n", SPI3.pin.val);
}

static void section_a_idf(void)
{
    spi_bus_config_t bus = {
        .mosi_io_num = 23, .miso_io_num = 19, .sclk_io_num = 18,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 64,
    };
    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 1000000, .mode = 0, .spics_io_num = 5, .queue_size = 1,
    };
    spi_device_handle_t h;
    spi_transaction_t t, *res;
    esp_err_t err;
    int64_t t0;

    printf("A: ESP-IDF spi_master on SPI3_HOST, SPI_DMA_DISABLED, CS GPIO5\n");
    ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_DISABLED));
    ESP_ERROR_CHECK(spi_bus_add_device(SPI3_HOST, &devcfg, &h));

    memset(&t, 0, sizeof(t));
    t.flags = SPI_TRANS_USE_RXDATA;
    t.length = 32;
    t.rxlength = 32;
    t0 = esp_timer_get_time();
    err = spi_device_polling_transmit(h, &t);
    printf("A1 polling rx-only: %s in %" PRId64 " us\n", esp_err_to_name(err), esp_timer_get_time() - t0);
    dump("A1 rx", t.rx_data, 4);

    memset(&t, 0, sizeof(t));
    t.flags = SPI_TRANS_USE_RXDATA | SPI_TRANS_USE_TXDATA;
    t.length = 32;
    memset(t.tx_data, 0xff, 4);
    err = spi_device_polling_transmit(h, &t);
    printf("A2 polling full-duplex tx ff ff ff ff: %s\n", esp_err_to_name(err));
    dump("A2 rx", t.rx_data, 4);

    memset(&t, 0, sizeof(t));
    t.flags = SPI_TRANS_USE_RXDATA | SPI_TRANS_USE_TXDATA;
    t.length = 32;
    t.tx_data[0] = 0x80;  /* register-sensor style: address byte with the read bit */
    err = spi_device_polling_transmit(h, &t);
    printf("A3 polling full-duplex tx 80 00 00 00: %s\n", esp_err_to_name(err));
    dump("A3 rx", t.rx_data, 4);

    /* Interrupt-driven path last: if it never completes, the device stays busy */
    memset(&t, 0, sizeof(t));
    t.flags = SPI_TRANS_USE_RXDATA;
    t.length = 32;
    t0 = esp_timer_get_time();
    err = spi_device_queue_trans(h, &t, pdMS_TO_TICKS(100));
    printf("A4 queue_trans (interrupt path): %s\n", esp_err_to_name(err));
    err = spi_device_get_trans_result(h, &res, pdMS_TO_TICKS(500));
    printf("A4 get_trans_result: %s after %" PRId64 " us\n", esp_err_to_name(err), esp_timer_get_time() - t0);
    if (err == ESP_OK) {
        dump("A4 rx", t.rx_data, 4);
    }
}

static void section_c_dma(void)
{
    spi_bus_config_t bus = {
        .mosi_io_num = 13, .miso_io_num = 12, .sclk_io_num = 14,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 4096,
    };
    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 1000000, .mode = 0, .spics_io_num = 15, .queue_size = 1,
    };
    spi_device_handle_t h;
    spi_transaction_t t;
    uint8_t *rx = heap_caps_malloc(64, MALLOC_CAP_DMA);
    esp_err_t err;
    int64_t t0;

    printf("C: ESP-IDF spi_master on SPI2_HOST, SPI_DMA_CH_AUTO, CS GPIO15\n");
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO));
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &devcfg, &h));

    memset(&t, 0, sizeof(t));
    t.flags = SPI_TRANS_USE_RXDATA;
    t.length = 32;
    t0 = esp_timer_get_time();
    err = spi_device_polling_transmit(h, &t);
    printf("C1 polling rx 4 bytes (RXDATA): %s in %" PRId64 " us\n", esp_err_to_name(err), esp_timer_get_time() - t0);
    dump("C1 rx", t.rx_data, 4);

    memset(rx, 0xa5, 64);
    memset(&t, 0, sizeof(t));
    t.length = 8 * 8;
    t.rx_buffer = rx;
    err = spi_device_polling_transmit(h, &t);
    printf("C2 polling rx 8 bytes into a DMA buffer prefilled a5: %s\n", esp_err_to_name(err));
    dump("C2 rx", rx, 8);
}

static volatile int s_isr_hits;

static void IRAM_ATTR on_edge(void *arg)
{
    s_isr_hits++;
}

static void section_d_gpio(void)
{
    gpio_config_t in = {
        .pin_bit_mask = 1ULL << 27, .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE, .intr_type = GPIO_INTR_NEGEDGE,
    };

    printf("D: GPIO\n");
    gpio_reset_pin(25);
    gpio_set_direction(25, GPIO_MODE_INPUT_OUTPUT);
    gpio_set_level(25, 1);
    printf("D1 after set_level(25, 1): GPIO_OUT=0x%08" PRIx32 " ENABLE=0x%08" PRIx32 " get_level(25)=%d\n",
           REG_READ(GPIO_OUT_REG), REG_READ(GPIO_ENABLE_REG), gpio_get_level(25));
    ESP_ERROR_CHECK(gpio_config(&in));
    printf("D2 GPIO27 input pull-up: get_level=%d GPIO_IN=0x%08" PRIx32 "\n",
           gpio_get_level(27), REG_READ(GPIO_IN_REG));
    printf("D3 install_isr_service: %s\n", esp_err_to_name(gpio_install_isr_service(0)));
    printf("D3 isr_handler_add(27): %s\n", esp_err_to_name(gpio_isr_handler_add(27, on_edge, NULL)));
    vTaskDelay(pdMS_TO_TICKS(50));
    printf("D3 isr hits after 50 ms: %d\n", s_isr_hits);
}

static void section_e_flash(void)
{
    nvs_handle_t nvs;
    uint32_t v = 0;
    uint8_t w[64], r[64];
    const esp_partition_t *part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                                           ESP_PARTITION_SUBTYPE_DATA_NVS, NULL);

    printf("E: flash on SPI1\n");
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(nvs_open("probe", NVS_READWRITE, &nvs));
    ESP_ERROR_CHECK(nvs_set_u32(nvs, "k", 0xC0FFEE42));
    ESP_ERROR_CHECK(nvs_commit(nvs));
    ESP_ERROR_CHECK(nvs_get_u32(nvs, "k", &v));
    printf("E1 nvs round trip: 0x%08" PRIx32 "\n", v);
    nvs_close(nvs);
    ESP_ERROR_CHECK(nvs_flash_deinit());

    for (int i = 0; i < 64; i++) {
        w[i] = (uint8_t)(i * 37 + 11);
    }
    ESP_ERROR_CHECK(esp_partition_erase_range(part, 0, part->erase_size));
    ESP_ERROR_CHECK(esp_partition_write(part, 3, w, sizeof(w)));
    ESP_ERROR_CHECK(esp_partition_read(part, 3, r, sizeof(r)));
    printf("E2 raw write/read 64 bytes at offset 3: %s\n", memcmp(w, r, 64) ? "MISMATCH" : "match");
}

void app_main(void)
{
    printf("PROBE start\n");
    section_b_arduino();
    section_a_idf();
    section_c_dma();
    section_d_gpio();
    section_e_flash();
    printf("PROBE_DONE\n");
}
