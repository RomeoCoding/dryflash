idf_component_register(SRCS "main.c" "ads1115.c" "lut.c" "tank.c" INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_timer esp_rom)
