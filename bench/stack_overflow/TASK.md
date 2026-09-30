# Signal statistics never prints its result

The firmware in this folder computes statistics over 5000 samples in a worker task and should print
one `stats: samples=5000 mean=... peak_bin=... peak_count=...` line, then `worker done`. On the
board it crashes or resets shortly after `signal statistics starting` instead.

Make it print the statistics and `worker done` without crashing. Don't change the sample
generator or the statistics being computed.
