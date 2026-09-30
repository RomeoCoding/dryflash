/* Command queue over UART0: an 8-slot ring buffer.
 *   put <n>   queue a number ("put: full" when there is no room)
 *   get       dequeue the oldest number
 *   dump      print the queue, oldest first
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define CAP 8

typedef struct {
    int buf[CAP];
    int head;   /* next write position */
    int tail;   /* oldest element */
    int count;
} ring_t;

static ring_t s_ring;

static int ring_put(ring_t *r, int v)
{
    if (r->count > CAP) {
        return -1;
    }
    r->buf[r->head] = v;
    r->head = (r->head + 1) % CAP;
    r->count++;
    return 0;
}

static int ring_get(ring_t *r, int *v)
{
    if (r->count == 0) {
        return -1;
    }
    *v = r->buf[r->tail];
    r->tail = (r->tail + 1) % CAP;
    r->count--;
    return 0;
}

static void ring_dump(const ring_t *r)
{
    printf("queue (%d):", r->count);
    for (int i = 0; i < r->count; i++) {
        printf(" %d", r->buf[(r->tail + i) % CAP]);
    }
    printf("\n");
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
    printf("queue ready\n");
    for (;;) {
        read_line(line, sizeof(line));
        if (strncmp(line, "put ", 4) == 0) {
            int v = atoi(line + 4);
            printf(ring_put(&s_ring, v) == 0 ? "put: ok %d\n" : "put: full\n", v);
        } else if (strcmp(line, "get") == 0) {
            int v;
            if (ring_get(&s_ring, &v) == 0) {
                printf("get: %d\n", v);
            } else {
                printf("get: empty\n");
            }
        } else if (strcmp(line, "dump") == 0) {
            ring_dump(&s_ring);
        } else {
            printf("unknown: %s\n", line);
        }
    }
}
