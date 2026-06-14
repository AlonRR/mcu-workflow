# NOTE: cJSON is no longer a core `json` component in ESP-IDF v6.0 - it is pulled
# in as the managed dependency espressif/cjson (see idf_component.yml), so it must
# NOT be listed in REQUIRES here.
# ESP-IDF v6.0 split the monolithic `driver` component into per-peripheral
# components, so depend on the specific ones this firmware includes:
#   driver/gpio.h            -> esp_driver_gpio
#   driver/usb_serial_jtag.h -> esp_driver_usb_serial_jtag
#   driver/ledc.h            -> esp_driver_ledc   (PWM signal generator)
idf_component_register(SRCS "satellite_main.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_wifi nvs_flash esp_netif esp_event
                                esp_driver_gpio esp_driver_usb_serial_jtag
                                esp_driver_ledc)
