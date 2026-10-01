# dryflash demo

Connected over stdio: 22 tools.

## 1. A crash, decoded

A config shell reboots when an operator types `set name` with no value.

**agent → `project_build`** `{"project_dir": "/tmp/dryflash-demo/null_config"}`
```json
{
  "ok": true,
  "duration_s": 74.7,
  "sizes": {
    "app_bin_bytes": 143456,
    "app_partition_bytes": 1048576,
    "app_partition_free_pct": 86.3,
    "memory": {
      "Flash Code": {
        "used": 52770
      },
      "IRAM": {
        "used": 44031,
        "total": 131072
      },
      "Flash Data": {
        "used": 35440
      },
      "DRAM": {
        "used": 13650,
        "total": 180736
      },
      "RTC SLOW": {
        "used": 64,
        "total": 8192
      }
    }
  }
}
```  (75.2s)

**agent → `emu_start`** `{"project_dir": "/tmp/dryflash-demo/null_config"}`
```json
{
  "session_id": "s1",
  "state": "running",
  "target": "esp32"
}
```  (0.3s)

**agent → `uart_expect`** `{"session_id": "s1", "pattern": "config shell ready", "timeout_s": 60}`
```json
{
  "matched": true,
  "match": "config shell ready"
}
```  (1.6s)

**agent → `uart_write`** `{"session_id": "s1", "text": "set name"}`
```json
{
  "bytes_written": 9,
  "uart_cursor_before_write": 2983
}
```  (0.0s)

**agent → `uart_expect`** `{"session_id": "s1", "pattern": "name=", "timeout_s": 10}`
```json
{
  "matched": false,
  "reason": "session exited: guest reset after a crash (see decode_panic)"
}
```  (0.0s)

**agent → `decode_panic`** `{"session_id": "s1"}`
```json
{
  "kind": "guru_meditation",
  "exception": "LoadProhibited",
  "cause": "NULL pointer dereference (read at 0x00000000) in apply_setting (main/main.c:21).",
  "backtrace": [
    {
      "pc": "0x4000164d",
      "function": null,
      "file": null,
      "line": null
    },
    {
      "pc": "0x400d5fa1",
      "function": "apply_setting",
      "file": "main/main.c",
      "line": 21
    },
    {
      "pc": "0x400d6022",
      "function": "handle",
      "file": "main/main.c",
      "line": 44
    },
    {
      "pc": "0x400d6069",
      "function": "app_main",
      "file": "main/main.c",
      "line": 81
    },
    {
      "pc": "0x400d3dfd",
      "function": "main_task",
      "file": "/opt/esp/idf/components/freertos/app_startup.c",
      "line": 206
    },
    {
      "pc": "0x400dad91",
      "function": "vPortTaskWrapper",
      "file": "/opt/esp/idf/components/freertos/FreeRTOS-Kernel/portable/xtensa/port.c",
      "line": 147
    }
  ]
}
```  (0.0s)

**agent → `emu_stop`** `{"session_id": "s1"}`
```json
{
  "state": "stopped"
}
```  (0.0s)

*agent edits the source:*
```diff
-        if (key == NULL) {
+        if (key == NULL || value == NULL) {
```

**agent → `test_run`** `{"project_dir": "/tmp/dryflash-demo/null_config", "scenario_file": "test/scenario.yaml"}`
```json
{
  "passed": true,
  "steps": [
    {
      "index": 0,
      "action": "expect",
      "name": null,
      "pattern": "config shell ready",
      "match": "config shell ready",
      "groups": [],
      "passed": true,
      "elapsed_s": 5.72
    },
    {
      "index": 1,
      "action": "write",
      "name": null,
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 2,
      "action": "expect",
      "name": null,
      "pattern": "error[^\\r\\n]*\\r?\\n",
      "match": "error: usage: set <key> <value>\r\n",
      "groups": [],
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 3,
      "action": "write",
      "name": null,
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 4,
      "action": "expect",
      "name": null,
      "pattern": "name=probe7\\r?\\n",
      "match": "name=probe7\r\n",
      "groups": [],
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 5,
      "action": "write",
      "name": null,
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 6,
      "action": "expect",
      "name": null,
      "pattern": "error[^\\r\\n]*\\r?\\n",
      "match": "error: usage: set <key> <value>\r\n",
      "groups": [],
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 7,
      "action": "write",
      "name": null,
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 8,
      "action": "expect",
      "name": null,
 
```  (9.3s)

## 2. A sensor bug no crash dump can show

A voltmeter reads an ADS1115 ADC over I2C. The test injects 1.234 V on AIN0, then 2.5 V at t = 3 s of virtual time.

**agent → `test_run`** `{"project_dir": "/tmp/dryflash-demo/adc_byte_order", "scenario_file": "test/scenario.yaml"}`
```json
{
  "passed": false,
  "failed_step": 0,
  "reason": "value -3.579 from 'ain0=-3.579 V' is outside [1.229, 1.239]"
}
```  (73.8s)

*agent edits the source:*
```diff
-    int16_t code = (int16_t)(b[1] << 8 | b[0]);
+    int16_t code = (int16_t)(b[0] << 8 | b[1]);   /* registers are big-endian */
```

**agent → `test_run`** `{"project_dir": "/tmp/dryflash-demo/adc_byte_order", "scenario_file": "test/scenario.yaml"}`
```json
{
  "passed": true,
  "steps": [
    {
      "index": 0,
      "action": "expect",
      "name": null,
      "pattern": "ain0=([-0-9.]+) V",
      "match": "ain0=1.234 V",
      "groups": [
        "1.234"
      ],
      "value": 1.234,
      "passed": true,
      "elapsed_s": 5.11
    },
    {
      "index": 1,
      "action": "sensor_set",
      "name": null,
      "result": {
        "sensor": "adc",
        "applies_from_ms": 3000.0,
        "channels": [
          "ain0"
        ],
        "resent_updates": 0
      },
      "passed": true,
      "elapsed_s": 0.0
    },
    {
      "index": 2,
      "action": "expect",
      "name": null,
      "pattern": "ain0=(2\\.\\d+) V",
      "match": "ain0=2.500 V",
      "groups": [
        "2.500"
      ],
      "value": 2.5,
      "passed": true,
      "elapsed_s": 0.33
    }
  ],
  "duration_s": 5.44
}
```  (9.5s)

Both bugs were found and fixed without a board: the crash from its decoded backtrace, the sensor bug from injected, deterministic ADC data.
