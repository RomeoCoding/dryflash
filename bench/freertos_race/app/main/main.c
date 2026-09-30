/* Packet counter: two receiver tasks each count 1000 packets into a shared total. */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#define PACKETS_PER_TASK 1000

static int s_total;
static EventGroupHandle_t s_done;
static EventGroupHandle_t s_link_up;

static void log_packet(void)
{
    /* Stand-in for the logging hook; gives the logger task a chance to run. */
    taskYIELD();
}

static void receiver(void *arg)
{
    int bit = (int)(intptr_t)arg;
    xEventGroupWaitBits(s_link_up, 1, pdFALSE, pdTRUE, portMAX_DELAY);   /* wait for the link */
    for (int i = 0; i < PACKETS_PER_TASK; i++) {
        int t = s_total;
        log_packet();
        s_total = t + 1;
    }
    xEventGroupSetBits(s_done, bit);
    vTaskDelete(NULL);
}

void app_main(void)
{
    s_done = xEventGroupCreate();
    s_link_up = xEventGroupCreate();
    printf("counting packets\n");
    xTaskCreatePinnedToCore(receiver, "rx_a", 3072, (void *)1, 5, NULL, 0);
    xTaskCreatePinnedToCore(receiver, "rx_b", 3072, (void *)2, 5, NULL, 0);
    xEventGroupSetBits(s_link_up, 1);
    xEventGroupWaitBits(s_done, 3, pdFALSE, pdTRUE, portMAX_DELAY);
    printf("total=%d (expected %d)\n", s_total, 2 * PACKETS_PER_TASK);
}
