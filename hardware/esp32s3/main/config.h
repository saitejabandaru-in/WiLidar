#ifndef WILIDAR_CONFIG_H
#define WILIDAR_CONFIG_H

#define WIFI_SSID           "WiLidar_Net"
#define WIFI_PASS           "wilidar_secure_pass"

// Target Python Server Details (RPi 5 or Dev Machine)
#define SERVER_IP           "192.168.1.100"
#define UDP_PORT            5005
#define HEARTBEAT_PORT      5006

// Unique identifier for this ESP32-S3 node (e.g., 1001, 1002)
// For deployment, change this per flashed node
#define NODE_ID             1001

// Target packet frequency (100 Hz = 1 ping / packet every 10ms)
#define CSI_PING_INTERVAL_MS 10

// FreeRTOS queue size for holding raw CSI frames before processing
#define CSI_QUEUE_LEN       64

// Preprocessing parameters
#define HAMPEL_WINDOW_HALF  5      // Hampel window size = 2 * half + 1 = 11 frames
#define HAMPEL_THRESHOLD_MAD 3.0f   // Outlier threshold multiplier
#define EMA_ALPHA           0.15f  // Exponential Moving Average weight [0.0, 1.0]

#endif // WILIDAR_CONFIG_H
