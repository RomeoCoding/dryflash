# Rapid-rise alarm does not trip

The hydraulic line monitor reads a 0-10 bar pressure transmitter (0.5-4.5 V) through AIN0 of an
ADS1115 (I2C0, SDA 21 / SCL 22, address 0x49). It must print
`ALARM: rapid pressure rise (<rate> bar/s) at t=<ms> ms` when the pressure rises at 5 bar/s or more.
On the test rig a 6.5 bar/s rise does not trip the alarm; only much faster rises do. The pressure
it reports agrees with the rig's reference gauge.

Make the alarm trip at 5 bar/s. Keep the 5 bar/s threshold, the three-sample confirmation and the
output formats. Rises slower than 5 bar/s must not trip it.
