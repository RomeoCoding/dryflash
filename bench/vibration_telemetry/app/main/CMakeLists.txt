idf_component_register(SRCS "main.c" "adxl345.c" "telemetry.c" "calib.c" INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c)
