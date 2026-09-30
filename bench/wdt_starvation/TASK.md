# Watchdog errors during warm-up

After boot the measurement sequencer waits for a 6 s warm-up and then takes five measurements.
Users report task watchdog errors (`task_wdt: Task watchdog got triggered`) in the log during
warm-up. The measurements must still come out after the warm-up, but without any watchdog
reports. The warm-up must stay 6 s.
