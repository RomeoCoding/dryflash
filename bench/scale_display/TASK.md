# Scale display sticks at the old weight

The platform scale reads its load cell through a NAU7802 ADC (I2C0, SDA 21 / SCL 22, address 0x2A,
80 SPS, 10,000 counts per kg at gain 128), tares at power-up and prints `weight=<kg> kg` every
100 ms. At the loading dock the display sometimes keeps showing the previous weight (usually
0.00 kg) after a sack is put on the platform, and only catches up when the sack is taken off again
or the unit is restarted. We could not reproduce it on the bench with test weights.

The display must follow any load that stays on the platform. Keep the knock rejection: knocks on
the platform lasting up to 30 ms must not show on the display.
