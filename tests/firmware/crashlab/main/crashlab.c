/*
 * crashlab: test firmware that crashes on command, so the panic decoder is checked against real
 * ESP-IDF output rather than hand-written samples. Commands arrive one per line on UART0.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static int *volatile g_null;
static volatile int g_zero;

__attribute__((noinline)) int read_sensor_value(void)
{
    return *g_null + 1;
}

__attribute__((noinline)) int divide(int a, int b)
{
    return a / b;
}

__attribute__((noinline)) static int recurse(int n)
{
    volatile char buf[256];
    memset((char *)buf, n, sizeof(buf));
    if (n == 0) {
        /* Block once at the bottom so the scheduler runs its stack-canary check. */
        vTaskDelay(1);
        return buf[3];
    }
    return recurse(n - 1) + buf[3];
}

static void overflow_task(void *arg)
{
    printf("recursed: %d\n", recurse(12));
    vTaskDelete(NULL);
}

static void spinner(void *arg)
{
    for (;;) {
    }
}

static void read_line(char *buf, size_t n)
{
    size_t i = 0;
    for (;;) {
        int c = getchar();
        if (c == EOF) {
            clearerr(stdin);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (c == '\n' || c == '\r') {
            if (i) {
                break;
            }
            continue;
        }
        if (i < n - 1) {
            buf[i++] = (char)c;
        }
    }
    buf[i] = '\0';
}

void app_main(void)
{
    char line[64];
    printf("crashlab ready\n");
    for (;;) {
        read_line(line, sizeof(line));
        if (strncmp(line, "echo ", 5) == 0) {
            printf("echo: %s\n", line + 5);
        } else if (strcmp(line, "null") == 0) {
            printf("value: %d\n", read_sensor_value());
        } else if (strcmp(line, "div0") == 0) {
            printf("value: %d\n", divide(10, g_zero));
        } else if (strcmp(line, "abort") == 0) {
            abort();
        } else if (strcmp(line, "assert") == 0) {
            assert(strlen(line) == 0);
        } else if (strcmp(line, "overflow") == 0) {
            xTaskCreate(overflow_task, "recurse", 2048, NULL, 5, NULL);
        } else if (strcmp(line, "wdt") == 0) {
            xTaskCreatePinnedToCore(spinner, "spinner", 2048, NULL, 5, NULL, 0);
        } else {
            printf("unknown command: %s\n", line);
        }
    }
}
