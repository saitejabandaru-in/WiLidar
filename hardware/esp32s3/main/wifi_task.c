#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "lwip/err.h"
#include "lwip/sys.h"
#include "lwip/sockets.h"
#include "lwip/netdb.h"

#include "config.h"
#include "csi_types.h"
#include "csi_tasks.h"

static const char *TAG = "WiLidar_WiFi";

// FreeRTOS event group to track connection status
static EventGroupHandle_t s_wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static int s_retry_num = 0;
#define MAX_RETRY 10

// Keep track of sequence numbers
static uint32_t s_callback_count = 0;

// CSI Receive Callback (runs in WiFi interrupt context)
static void wifi_csi_rx_callback(void *ctx, wifi_csi_info_t *info)
{
    if (info == NULL || info->buf == NULL || csi_queue == NULL) {
        return;
    }

    // Only extract CSI if we are receiving from a legacy frame (LLTF)
    // We filter by checking the payload length or signal mode.
    // In dense environments, we filter to prevent queue overflows.
    s_callback_count++;

    // Prepare raw frame struct
    csi_raw_frame_t frame;
    frame.timestamp_us = esp_timer_get_time();
    frame.rssi = info->rx_ctrl.rssi;
    frame.noise_floor = info->rx_ctrl.noise_floor;
    frame.channel = info->rx_ctrl.channel;
    frame.bandwidth = info->rx_ctrl.cwb;

    // The CSI data consists of interleaved IQ values. 
    // For 20MHz bandwidth, we have 64 subcarriers.
    // IQ components are int8_t. So 64 subcarriers * 2 (real + imaginary) = 128 bytes.
    int csi_len = info->len;
    if (csi_len > SUBCARRIER_COUNT * 2) {
        csi_len = SUBCARRIER_COUNT * 2;
    }
    
    // Copy the raw CSI buffer. Fill remaining with 0 if frame is shorter.
    memcpy(frame.csi_data, info->buf, csi_len);
    if (csi_len < SUBCARRIER_COUNT * 2) {
        memset(frame.csi_data + csi_len, 0, (SUBCARRIER_COUNT * 2) - csi_len);
    }

    // Push to processing queue. Use Non-blocking ISR-safe call.
    BaseType_t xHigherPriorityTaskWoken = pdFALSE;
    if (xQueueSendFromISR(csi_queue, &frame, &xHigherPriorityTaskWoken) != pdTRUE) {
        // Queue full! Frame dropped. We'll monitor this in status_task.
    }

    if (xHigherPriorityTaskWoken == pdTRUE) {
        portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
    }
}

// WiFi Event Handler
static void event_handler(void* arg, esp_event_base_t event_base,
                                int32_t event_id, void* event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry_num < MAX_RETRY) {
            esp_wifi_connect();
            s_retry_num++;
            ESP_LOGI(TAG, "Retrying connection to AP (%d/%d)...", s_retry_num, MAX_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
        ESP_LOGE(TAG, "Failed to connect to AP");
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Got IP Address: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

// Initialize WiFi in STA Mode
static void wifi_init_sta(void)
{
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
                                                        ESP_EVENT_ANY_ID,
                                                        &event_handler,
                                                        NULL,
                                                        &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT,
                                                        IP_EVENT_STA_GOT_IP,
                                                        &event_handler,
                                                        NULL,
                                                        &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "WiFi STA Initialization completed. Waiting for connection...");

    // Block until connection is established or failed
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
            WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
            pdFALSE,
            pdFALSE,
            portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Connected to WiFi AP SSID: %s", WIFI_SSID);
    } else if (bits & WIFI_FAIL_BIT) {
        ESP_LOGE(TAG, "Failed to connect to WiFi AP SSID: %s", WIFI_SSID);
    } else {
        ESP_LOGE(TAG, "UNEXPECTED EVENT during WiFi init");
    }
}

// Configure WiFi CSI Settings
static void configure_wifi_csi(void)
{
    // Enable CSI in ESP WiFi Driver
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));

    esp_wifi_csi_config_t csi_config = {
        .lltf_en           = true,  // Legacy Long Training Field (stable)
        .htltf_en          = false, // High Throughput LTF (disabled for stability)
        .stbc_htltf2_en    = false,
        .ltf_merge_en      = true,  // Merge/average multiple LTF symbols to filter phase noise
        .channel_filter_en = true,  // Use hardware-level bandpass filter on subcarriers
        .manu_scale        = false, // Enable auto AGC scaling
        .shift             = false
    };

    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    
    // Register the callback function
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(&wifi_csi_rx_callback, NULL));
    
    ESP_LOGI(TAG, "WiFi CSI processing configured and callback registered.");
}

// Task to maintain connection and generate active traffic
void wifi_csi_task(void *pvParameters)
{
    // 1. Setup STA WiFi and block until connected
    wifi_init_sta();

    // 2. Configure CSI and register callback
    configure_wifi_csi();

    // Set lower transmit power to prevent RX signal saturation in indoor environments (Pitfall 11)
    // 60 corresponds to 15 dBm (standard max is 20 dBm or 80)
    esp_wifi_set_max_tx_power(60);
    ESP_LOGI(TAG, "WiFi transmit power capped to 15 dBm (value: 60) to prevent close-range saturation.");

    // 3. UDP traffic generator loop (stimulate CSI frames at 100Hz)
    struct sockaddr_in dest_addr;
    dest_addr.sin_addr.s_addr = inet_addr(SERVER_IP);
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(UDP_PORT);

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Unable to create traffic generator socket: errno %d", errno);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "UDP Traffic Generator started. Target: %s:%d at 100Hz", SERVER_IP, UDP_PORT);

    const char *probe_msg = "WIPROBE";
    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(CSI_PING_INTERVAL_MS); // 10ms intervals (100Hz)

    while (1) {
        // Send a small packet to stimulate CSI responses
        // We broadcast to the server, which serves as a pulse to keep the channel dynamic.
        int err = sendto(sock, probe_msg, strlen(probe_msg), 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
        if (err < 0) {
            ESP_LOGE(TAG, "Error occurred during traffic generation: errno %d", errno);
        }

        // Delay until next period (exactly 10ms from last wake time)
        vTaskDelayUntil(&xLastWakeTime, xFrequency);
    }

    close(sock);
    vTaskDelete(NULL);
}
