# Command queue corrupts data when full

The UART command queue holds 8 numbers (`put <n>`, `get`, `dump`; see the comment in main.c). After
8 successful puts, a ninth `put` should answer `put: full` and leave the queue unchanged, but
users see the queue contents get mangled (`dump` shows wrong or duplicated values). Fix it so the
queue keeps its 8 values in order and rejects additional puts with `put: full`.
