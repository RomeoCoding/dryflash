idf_component_register(SRCS "spi_probe.c" INCLUDE_DIRS "." PRIV_REQUIRES esp_driver_spi esp_driver_gpio esp_timer nvs_flash esp_partition)
