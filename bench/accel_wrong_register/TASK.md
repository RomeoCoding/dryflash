# Tilt meter shows nonsense angles

The tilt meter reads an ADXL345 accelerometer over I2C and prints the tilt from vertical every
200 ms (`tilt=<degrees> deg`). Held level it should read about 0, tilted 45 degrees about 45, and
on its side about 90. The printed angles don't match the real orientation. Fix the reading.
