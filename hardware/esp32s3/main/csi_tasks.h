#ifndef WILIDAR_CSI_TASKS_H
#define WILIDAR_CSI_TASKS_H

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "csi_types.h"

// Shared queue handle for raw CSI data communication
extern QueueHandle_t csi_queue;

// Task declarations
void wifi_csi_task(void *pvParameters);
void processing_task(void *pvParameters);
void status_task(void *pvParameters);

#endif // WILIDAR_CSI_TASKS_H
