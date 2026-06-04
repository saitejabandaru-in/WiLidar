idf_component_register(SRCS "csi_collector.c"
                            "wifi_task.c"
                            "processing_task.c"
                            "status_task.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_wifi nvs_flash lwip driver led_strip)
