idf_component_register(SRCS "main.c" "nau7802.c" "filter.c" INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c)
