# Humidity logger stops publishing

The logger samples an HDC1080 humidity and temperature sensor (I2C0, SDA 21 / SCL 22, address 0x40)
and prints `t=<s> s rh=<%> % temp=<C> C (<n> records)` once a second. Units on the bench look
fine, but units left running start printing `sensor fault: no fresh data` about a minute after
power-up, every second, and publish no reading until they are reset. The sensors are fine: after a
reset the same unit works again for a while.

Make the logger keep publishing current readings for as long as it runs. Keep the output format,
and keep the stale-data check: it must still report a fault if the sensor stops delivering.
