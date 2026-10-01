#pragma once
#include "driver/i2c_master.h"
#include "esp_err.h"

esp_err_t ads1115_init(i2c_master_bus_handle_t bus);
/* One single-shot conversion of AIN0 against GND on the +-6.144 V range, in volts. */
esp_err_t ads1115_read_ain0(float *volts);
