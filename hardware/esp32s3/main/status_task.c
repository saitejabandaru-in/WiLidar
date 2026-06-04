#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "lwip/err.h"
#include "lwip/sockets.h"

// If led_strip.h is present, we use the official driver. 
// Otherwise we log status messages to serial.
#if __has_include("led_strip.h")
#include "led_strip.h"
static led_strip_handle_t s_led_strip = NULL;
#define HAS_LED_STRIP 1
#else
#define HAS_LED_STRIP 0
#endif

#include "config.h"
#include "csi_types.h"
#include "csi_tasks.h"

static const char *TAG = "WiLidar_Status";

// LED Colors
typedef enum {
    LED_COLOR_BLUE,   // Booting / Connecting
    LED_COLOR_GREEN,  // Connected / Collecting CSI
    LED_COLOR_RED,    // Error / Disconnected
    LED_COLOR_WHITE,  // Presence Detected
    LED_COLOR_PURPLE  // Data sent/processing active
} led_status_color_t;

// Set LED color helper function
static void set_led_status(led_status_color_t color)
{
#if HAS_LED_STRIP
    if (s_led_strip == NULL) {
        return;
    }
    uint8_t r = 0, g = 0, b = 0;
    switch (color) {
        case LED_COLOR_BLUE:
            r = 0; g = 0; b = 255;
            break;
        case LED_COLOR_GREEN:
            r = 0; g = 255; b = 0;
            break;
        case LED_COLOR_RED:
            r = 255; g = 0; b = 0;
            break;
        case LED_COLOR_WHITE:
            r = 255; g = 255; b = 255;
            break;
        case LED_COLOR_PURPLE:
            r = 255; g = 0; b = 255;
            break;
    }
    led_strip_set_pixel(s_led_strip, 0, r, g, b);
    led_strip_refresh(s_led_strip);
#else
    switch (color) {
        case LED_COLOR_BLUE:
            ESP_LOGD(TAG, "[LED] BLUE (Connecting)");
            break;
        case LED_COLOR_GREEN:
            ESP_LOGD(TAG, "[LED] GREEN (Normal)");
            break;
        case LED_COLOR_RED:
            ESP_LOGD(TAG, "[LED] RED (Error)");
            break;
        case LED_COLOR_WHITE:
            ESP_LOGD(TAG, "[LED] WHITE (Presence)");
            break;
        case LED_COLOR_PURPLE:
            ESP_LOGD(TAG, "[LED] PURPLE (Processing)");
            break;
    }
#endif
}

// Watchdog & Heartbeat loop
void status_task(void *pvParameters)
{
    // Initialize LED strip if available
#if HAS_LED_STRIP
    led_strip_config_t strip_config = {
        .strip_gpio_num = 3, // GPIO 3 as defined in physical wiring rules
        .max_leds = 1,
    };
    led_strip_rmt_config_t rmt_config = {
        .resolution_hz = 10 * 1000 * 1000, // 10MHz
    };
    esp_err_t err = led_strip_new_rmt_device(&strip_config, &rmt_config, &s_led_strip);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to initialize WS2812 LED Strip: %s", esp_err_to_name(err));
    }
#endif

    set_led_status(LED_COLOR_BLUE);

    // Create UDP Socket for Heartbeat
    struct sockaddr_in dest_addr;
    dest_addr.sin_addr.s_addr = inet_addr(SERVER_IP);
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(HEARTBEAT_PORT);

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Unable to create Heartbeat socket: errno %d", errno);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "Heartbeat watchdog task started. Pinging %s:%d every 5s", SERVER_IP, HEARTBEAT_PORT);

    int queue_full_counter = 0;
    int loop_counter = 0;

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000)); // Every 5 seconds

        // Check WiFi status
        wifi_ap_record_t ap_info;
        esp_err_t wifi_err = esp_wifi_sta_get_ap_info(&ap_info);

        if (wifi_err != ESP_OK) {
            ESP_LOGW(TAG, "WiFi connection lost! Status LED set to RED.");
            set_led_status(LED_COLOR_RED);
            // Reconnect is handled automatically by the wifi_event_handler in STA config
            continue;
        }

        // WiFi is OK, update status based on data queue
        uint32_t queue_fill = uxQueueMessagesWaiting(csi_queue);
        loop_counter++;

        if (loop_counter % 6 == 0) { // Every 30 seconds (Pitfall 2 check)
            ESP_LOGI(TAG, "Watchdog status: Queue utilization %d/%d frames. RSSI: %d dBm", 
                     (int)queue_fill, CSI_QUEUE_LEN, ap_info.rssi);
        }

        // Watchdog to prevent core lockups (self-heal)
        if (queue_fill >= CSI_QUEUE_LEN - 2) {
            queue_full_counter++;
            set_led_status(LED_COLOR_RED);
            ESP_LOGW(TAG, "Queue warning! Queue almost full (%d/%d). Count: %d", 
                     (int)queue_fill, CSI_QUEUE_LEN, queue_full_counter);
            
            if (queue_full_counter >= 3) { // 15 seconds of blocked queue
                ESP_LOGE(TAG, "Queue processing has fallen behind for 15s. Resetting queue to prevent OOM.");
                xQueueReset(csi_queue);
                queue_full_counter = 0;
            }
        } else {
            queue_full_counter = 0;
            set_led_status(LED_COLOR_GREEN);
        }

        // Send Heartbeat Packet
        // Layout: uint32 node_id, uint32 queue_fill_percent, int32 rssi
        uint32_t hb_payload[3];
        hb_payload[0] = NODE_ID;
        hb_payload[1] = (queue_fill * 100) / CSI_QUEUE_LEN;
        hb_payload[2] = (int32_t)ap_info.rssi;

        int sent = sendto(sock, hb_payload, sizeof(hb_payload), 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
        if (sent < 0) {
            ESP_LOGE(TAG, "Heartbeat failed to send: errno %d", errno);
        } else {
            // Heartbeat succeeded, blink Purple momentarily to show telemetry is sending
            set_led_status(LED_COLOR_PURPLE);
            vTaskDelay(pdMS_TO_TICKS(100));
            set_led_status(LED_COLOR_GREEN);
        }
    }

    close(sock);
    vTaskDelete(NULL);
}
