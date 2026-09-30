/* Device configuration shell over UART0.
 *   set <key> <value>   keys: name, rate
 *   show                print the configuration
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef struct {
    char name[32];
    int rate;
} config_t;

static config_t s_cfg = {.name = "node", .rate = 10};

static void apply_setting(config_t *cfg, const char *key, const char *value)
{
    if (strcmp(key, "name") == 0) {
        strncpy(cfg->name, value, sizeof(cfg->name) - 1);
        printf("name=%s\n", cfg->name);
    } else if (strcmp(key, "rate") == 0) {
        cfg->rate = atoi(value);
        printf("rate=%d\n", cfg->rate);
    } else {
        printf("error: unknown key '%s'\n", key);
    }
}

static void handle(char *line)
{
    char *cmd = strtok(line, " ");
    if (cmd == NULL) {
        return;
    }
    if (strcmp(cmd, "set") == 0) {
        char *key = strtok(NULL, " ");
        char *value = strtok(NULL, " ");
        if (key == NULL) {
            printf("error: usage: set <key> <value>\n");
            return;
        }
        apply_setting(&s_cfg, key, value);
    } else if (strcmp(cmd, "show") == 0) {
        printf("config: name=%s rate=%d\n", s_cfg.name, s_cfg.rate);
    } else {
        printf("error: unknown command '%s'\n", cmd);
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
    char line[96];
    printf("config shell ready\n");
    for (;;) {
        read_line(line, sizeof(line));
        handle(line);
    }
}
