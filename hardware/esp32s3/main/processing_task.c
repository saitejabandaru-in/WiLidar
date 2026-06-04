#include <stdio.h>
#include <math.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_rom_crc.h"
#include "lwip/err.h"
#include "lwip/sockets.h"

#include "config.h"
#include "csi_types.h"
#include "csi_tasks.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

static const char *TAG = "WiLidar_Proc";

// Helper function to swap two floats (for bubble sort)
static void swap_float(float *xp, float *yp)
{
    float temp = *xp;
    *xp = *yp;
    *yp = temp;
}

// Simple bubble sort to find median of a small float array
static void sort_float(float arr[], int n)
{
    for (int i = 0; i < n-1; i++) {
        for (int j = 0; j < n-i-1; j++) {
            if (arr[j] > arr[j+1]) {
                swap_float(&arr[j], &arr[j+1]);
            }
        }
    }
}

// Preprocessing state per subcarrier
typedef struct {
    float window[10]; // Sliding window of recent amplitudes
    int window_index;
    int window_filled;
    float ema_amplitude;
    float min_amp;
    float max_amp;
} subcarrier_state_t;

static subcarrier_state_t s_states[SUBCARRIER_COUNT];
static uint32_t s_seq_num = 0;

// Hampel filter implementation for a single subcarrier amplitude
static float apply_hampel(subcarrier_state_t *state, float new_val)
{
    // Append to circular buffer window
    state->window[state->window_index] = new_val;
    state->window_index = (state->window_index + 1) % 10;
    if (!state->window_filled && state->window_index == 0) {
        state->window_filled = 1;
    }

    int count = state->window_filled ? 10 : state->window_index;
    if (count < 3) {
        return new_val; // Not enough data, return as-is
    }

    // Copy window to temp array for sorting
    float temp[10];
    memcpy(temp, state->window, count * sizeof(float));
    sort_float(temp, count);

    // Calculate Median
    float median;
    if (count % 2 == 0) {
        median = (temp[count / 2 - 1] + temp[count / 2]) / 2.0f;
    } else {
        median = temp[count / 2];
    }

    // Calculate Median Absolute Deviation (MAD)
    float abs_dev[10];
    for (int i = 0; i < count; i++) {
        abs_dev[i] = fabsf(state->window[i] - median);
    }
    sort_float(abs_dev, count);

    float mad;
    if (count % 2 == 0) {
        mad = (abs_dev[count / 2 - 1] + abs_dev[count / 2]) / 2.0f;
    } else {
        mad = abs_dev[count / 2];
    }

    // Threshold test
    float threshold = HAMPEL_THRESHOLD_MAD * mad;
    if (fabsf(new_val - median) > threshold && mad > 0.001f) {
        return median; // Outlier detected, return median
    }

    return new_val;
}

// Processing task logic
void processing_task(void *pvParameters)
{
    // Initialize states
    for (int i = 0; i < SUBCARRIER_COUNT; i++) {
        s_states[i].window_index = 0;
        s_states[i].window_filled = 0;
        s_states[i].ema_amplitude = 0.0f;
        s_states[i].min_amp = 9999.0f;
        s_states[i].max_amp = -9999.0f;
    }

    // Create UDP Socket for sending structured CSI packets
    struct sockaddr_in dest_addr;
    dest_addr.sin_addr.s_addr = inet_addr(SERVER_IP);
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(UDP_PORT);

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Unable to create UDP transmission socket: errno %d", errno);
        vTaskDelete(NULL);
        return;
    }

    // Configure socket for non-blocking / buffered writes
    int opt_val = 1;
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &opt_val, sizeof(opt_val));

    ESP_LOGI(TAG, "UDP Processing Task initialized. Exporting data to %s:%d", SERVER_IP, UDP_PORT);

    csi_raw_frame_t raw_frame;
    csi_udp_packet_t out_packet;

    while (1) {
        // Blocks until a frame is available in the queue
        if (xQueueReceive(csi_queue, &raw_frame, portMAX_DELAY) == pdTRUE) {
            
            out_packet.node_id = NODE_ID;
            out_packet.sequence_number = s_seq_num++;
            out_packet.timestamp_us = raw_frame.timestamp_us;
            out_packet.rssi = raw_frame.rssi;
            out_packet.noise_floor = raw_frame.noise_floor;
            out_packet.channel = raw_frame.channel;
            out_packet.bandwidth = raw_frame.bandwidth;

            // Process each of the 64 subcarriers
            for (int i = 0; i < SUBCARRIER_COUNT; i++) {
                // Interleaved IQ values
                float real = (float)raw_frame.csi_data[2 * i];
                float imag = (float)raw_frame.csi_data[2 * i + 1];

                // 1. Amplitude & Phase extraction
                float amp = sqrtf(real * real + imag * imag);
                float phase = atan2f(imag, real); // returns [-PI, PI]

                // 2. Outlier Rejection (Hampel Filter)
                float filtered_amp = apply_hampel(&s_states[i], amp);

                // 3. Smooth (Exponential Moving Average)
                if (s_states[i].ema_amplitude == 0.0f) {
                    s_states[i].ema_amplitude = filtered_amp;
                } else {
                    s_states[i].ema_amplitude = (EMA_ALPHA * filtered_amp) + ((1.0f - EMA_ALPHA) * s_states[i].ema_amplitude);
                }

                // 4. Session min/max tracking for normalization
                if (s_states[i].ema_amplitude < s_states[i].min_amp) {
                    s_states[i].min_amp = s_states[i].ema_amplitude;
                }
                if (s_states[i].ema_amplitude > s_states[i].max_amp) {
                    s_states[i].max_amp = s_states[i].ema_amplitude;
                }

                // Normalization to [0.0, 1.0] range (protect against divide by zero)
                float norm_amp = 0.0f;
                float amp_range = s_states[i].max_amp - s_states[i].min_amp;
                if (amp_range > 0.001f) {
                    norm_amp = (s_states[i].ema_amplitude - s_states[i].min_amp) / amp_range;
                }

                // 5. Serialize into packed binary formats
                // Scale normalized amplitude [0, 1] to [0, 127] for int8_t
                out_packet.amplitudes[i] = (int8_t)(norm_amp * 127.0f);

                // Map phase [-PI, PI] to [-128, 127] for int8_t
                float norm_phase = phase / M_PI; // returns [-1, 1]
                out_packet.phases[i] = (int8_t)(norm_phase * 127.0f);
            }

            // 6. Compute CRC32 for transmission verification
            out_packet.crc32 = esp_rom_crc32_le(
                0, 
                (uint8_t*)&out_packet, 
                offsetof(csi_udp_packet_t, crc32)
            );

            // 7. Fire-and-forget UDP delivery (non-blocking)
            int sent_bytes = sendto(
                sock, 
                &out_packet, 
                sizeof(out_packet), 
                0, 
                (struct sockaddr *)&dest_addr, 
                sizeof(dest_addr)
            );

            if (sent_bytes < 0) {
                // If the socket buffer is full, drop it and keep going (prevents lockups)
                ESP_LOGD(TAG, "UDP send buffer full, packet dropped");
            }
        }
    }

    close(sock);
    vTaskDelete(NULL);
}
