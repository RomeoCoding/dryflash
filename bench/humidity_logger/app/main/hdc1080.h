#pragma once
#include "driver/i2c_master.h"
#include "esp_err.h"

esp_err_t hdc1080_init(i2c_master_bus_handle_t bus);
/* Triggers one temperature + humidity conversion and waits for it (about 20 ms). */
esp_err_t hdc1080_read(float *rh, float *temp_c);
