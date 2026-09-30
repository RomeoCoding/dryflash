/* Minimal example: print a greeting and a counter. Used by the quickstart and the smoke test. */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static int counter;

static void tick(void)
{
    counter++;
    printf("tick %d\n", counter);
}

void app_main(void)
{
    printf("Hello from dryflash!\n");
    for (int i = 0; i < 5; i++) {
        tick();
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    printf("done\n");
}
