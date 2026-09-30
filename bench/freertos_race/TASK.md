# Packet counter loses packets

Two receiver tasks each count 1000 packets into a shared total, so the firmware should print
`total=2000 (expected 2000)`. It prints a smaller total. Make the count exact. Keep both receiver
tasks and the `log_packet()` hook.
