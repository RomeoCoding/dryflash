#pragma once
#include "driver/i2c_master.h"

esp_err_t oled_init(i2c_master_bus_handle_t bus, uint8_t address);
void oled_clear(void);
/* Text in the Adafruit-GFX classic 5x7 font; size scales each pixel to size x size */
void oled_text(int x, int y, int size, const char *s);
esp_err_t oled_flush(void);
