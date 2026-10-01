# Tank gauge volume jumps during refills

The tank gauge reads a hydrostatic level transmitter (0.5 V empty, 4.5 V at 2000 mm) through AIN0
of an ADS1115 (I2C0, SDA 21 / SCL 22, address 0x49) and prints
`t=<s> s level=<mm> mm vol=<litres> L` once a second for the site's 18,850 L tank. During refills
the volume repeatedly drops back by several hundred litres and climbs again, and after a refill
the gauge often shows several hundred litres less than the delivery note. The transmitter and its
wiring have been checked. The site's data logger recorded the transmitter output during one refill:
`data/refill_2026-09-12.csv` (time in s, volts).

Make the gauge show the tank's content correctly. Keep the output format.
