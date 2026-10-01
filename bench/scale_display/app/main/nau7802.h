#pragma once
#include <stdint.h>
#include "driver/i2c_master.h"
#include "esp_err.h"

/* Resets and powers up the ADC: gain 128, 80 SPS, conversions running. */
esp_err_t nau7802_init(i2c_master_bus_handle_t bus);
/* Waits for the next conversion and returns it as a signed 24-bit count. */
esp_err_t nau7802_read(int32_t *counts);
