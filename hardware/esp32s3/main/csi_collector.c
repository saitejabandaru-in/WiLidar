#include <stdio.h>
#include "nvs_flash.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "config.h"
#include "csi_types.h"
#include "csi_tasks.h"

static const char *TAG = "WiLidar_Main";

// Define the global queue handle
QueueHandle_t csi_queue = NULL;

void app_main(void)
{
    ESP_LOGI(TAG, "Starting WiLidar Firmware on Node ID: %d", NODE_ID);

    // 1. Initialize Non-Volatile Storage (NVS)
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // 2. Create the FreeRTOS Queue for buffering raw CSI frames
    // The queue will hold up to CSI_QUEUE_LEN (64) frames.
    csi_queue = xQueueCreate(CSI_QUEUE_LEN, sizeof(csi_raw_frame_t));
    if (csi_queue == NULL) {
        ESP_LOGE(TAG, "Failed to create CSI Frame Queue! Halting...");
        return;
    }
    ESP_LOGI(TAG, "CSI Frame Queue created successfully with length: %d", CSI_QUEUE_LEN);

    // 3. Spawn FreeRTOS Tasks
    // Task 1: WiFi and CSI collection (Highest Priority, Core 0)
    xTaskCreatePinnedToCore(
        wifi_csi_task,
        "wifi_csi_task",
        8192,
        NULL,
        5, // Highest Priority
        NULL,
        0  // Pin to Core 0 (alongside WiFi driver operations)
    );

    // Task 2: Signal processing, filtering, and UDP transmission (Medium Priority, Core 1)
    xTaskCreatePinnedToCore(
        processing_task,
        "processing_task",
        16384,
        NULL,
        3, // Medium Priority
        NULL,
        1  // Pin to Core 1 (isolated from WiFi operations to avoid processing bottlenecks)
    );

    // Task 3: Watchdog, Heartbeat, and RGB LED indicator (Lowest Priority, Core 0)
    xTaskCreatePinnedToCore(
        status_task,
        "status_task",
        4096,
        NULL,
        1, // Lowest Priority
        NULL,
        0  // Pin to Core 0
    );

    ESP_LOGI(TAG, "All tasks spawned successfully. Running WiLidar monitoring.");
}
