idf_component_register(SRCS "main.c" "hdc1080.c" "log.c" INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_timer)
