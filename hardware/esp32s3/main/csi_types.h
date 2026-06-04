#ifndef WILIDAR_CSI_TYPES_H
#define WILIDAR_CSI_TYPES_H

#include <stdint.h>

#define SUBCARRIER_COUNT 64

// Struct for passing raw CSI data from the interrupt-context callback to wifi_csi_task
typedef struct {
    int64_t timestamp_us;
    int8_t rssi;
    int8_t noise_floor;
    uint8_t channel;
    uint8_t bandwidth;
    int8_t csi_data[SUBCARRIER_COUNT * 2]; // interleaved real/imaginary or raw IQ
} csi_raw_frame_t;

// Packed UDP packet payload structural layout (exactly 152 bytes)
typedef struct __attribute__((packed)) {
    uint32_t node_id;
    uint32_t sequence_number;
    int64_t timestamp_us;
    int8_t rssi;
    int8_t noise_floor;
    uint8_t channel;
    uint8_t bandwidth;
    int8_t amplitudes[SUBCARRIER_COUNT];
    int8_t phases[SUBCARRIER_COUNT];
    uint32_t crc32;
} csi_udp_packet_t;

#endif // WILIDAR_CSI_TYPES_H
