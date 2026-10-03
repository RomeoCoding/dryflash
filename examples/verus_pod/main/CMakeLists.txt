idf_component_register(SRCS "verus_pod.c" "oled.c" INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_driver_spi esp_driver_gpio esp_timer)
