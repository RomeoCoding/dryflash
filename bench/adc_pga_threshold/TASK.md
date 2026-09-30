# Battery monitor always says LOW BATTERY

The battery (a 3.0-4.2 V Li-ion cell) feeds AIN1 of an ADS1115 through a 2:1 divider. The monitor
prints `battery=<volts> V` every 200 ms and `LOW BATTERY` below 3.4 V. With a full-ish 3.8 V
battery it reports about half the voltage and flags LOW BATTERY. Make the reported voltage
correct. The 3.4 V threshold stays.
