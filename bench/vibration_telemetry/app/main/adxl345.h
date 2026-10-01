#pragma once
#include <stdint.h>
#include "driver/i2c_master.h"
#include "esp_err.h"

/* +-16 g, full resolution (3.9 mg/LSB), 400 Hz output data rate, measuring. */
esp_err_t adxl345_init(i2c_master_bus_handle_t bus);
esp_err_t adxl345_read_raw(int16_t raw[3]);
