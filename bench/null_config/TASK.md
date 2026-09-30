# Config shell reboots on a typo

The configuration shell on UART0 accepts `set <key> <value>` and `show`. When an operator forgets
the value (for example `set name`), the device crashes and reboots. A command with a missing value
must print an error line starting with `error` and leave the configuration unchanged, and the
shell must keep working afterwards.
