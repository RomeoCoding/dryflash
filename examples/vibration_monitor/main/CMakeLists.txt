idf_component_register(SRCS "vibration_monitor.c" INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_timer)
