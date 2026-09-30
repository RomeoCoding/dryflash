# Shock detector misses shocks

The shock detector uses an ADXL345 on its +-8 g range. At rest it should print `z=1.00 g` (gravity)
and it must print `ALARM: shock ...` whenever an axis exceeds 2 g. At rest it prints a Z value far
below 1 g, and real 3 g shocks never raise the alarm. Keep the +-8 g range and the 2 g threshold.
