/*
 * Minimal SSD1306 128x64 driver: a 1 KB frame buffer, the Adafruit-GFX 5x7 font at integer
 * sizes, and a flush in 31-byte data transfers (control byte 0x40 first), the chunking the
 * Adafruit library uses on ESP32. Command bytes follow the SSD1306 datasheet Rev 1.1, section 9.
 */
#include <string.h>
#include "oled.h"
#include "font5x7.h"

#define W 128
#define PAGES 8

static i2c_master_dev_handle_t s_dev;
static uint8_t s_fb[W * PAGES];

static esp_err_t commands(const uint8_t *cmd, size_t n)
{
    uint8_t buf[32] = {0x00};   /* Co = 0, D/C# = 0: the rest of the transfer is commands */
    memcpy(buf + 1, cmd, n);
    return i2c_master_transmit(s_dev, buf, n + 1, 100);
}

esp_err_t oled_init(i2c_master_bus_handle_t bus, uint8_t address)
{
    static const uint8_t init[] = {
        0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00,
        0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF,
    };
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = address, .scl_speed_hz = 400000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &s_dev);
    if (err != ESP_OK) {
        return err;
    }
    oled_clear();
    return commands(init, sizeof(init));
}

void oled_clear(void)
{
    memset(s_fb, 0, sizeof(s_fb));
}

static void pixel(int x, int y)
{
    if (x >= 0 && x < W && y >= 0 && y < PAGES * 8) {
        s_fb[(y / 8) * W + x] |= 1 << (y % 8);
    }
}

void oled_text(int x, int y, int size, const char *s)
{
    for (; *s; s++, x += 6 * size) {
        unsigned c = (unsigned char)*s;
        if (c < 0x20 || c > 0x7E) {
            c = '?';
        }
        const uint8_t *g = &font5x7[(c - 0x20) * 5];
        for (int col = 0; col < 5; col++) {
            for (int row = 0; row < 8; row++) {
                if (g[col] >> row & 1) {
                    for (int dx = 0; dx < size; dx++) {
                        for (int dy = 0; dy < size; dy++) {
                            pixel(x + col * size + dx, y + row * size + dy);
                        }
                    }
                }
            }
        }
    }
}

esp_err_t oled_flush(void)
{
    static const uint8_t window[] = {0x21, 0, W - 1, 0x22, 0, PAGES - 1};
    uint8_t buf[32] = {0x40};   /* Co = 0, D/C# = 1: data */
    esp_err_t err = commands(window, sizeof(window));

    for (size_t i = 0; i < sizeof(s_fb) && err == ESP_OK; i += 31) {
        size_t n = sizeof(s_fb) - i < 31 ? sizeof(s_fb) - i : 31;
        memcpy(buf + 1, s_fb + i, n);
        err = i2c_master_transmit(s_dev, buf, n + 1, 100);
    }
    return err;
}
