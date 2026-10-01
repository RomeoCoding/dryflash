# Vibration logger reboots on the crusher

The vibration logger (ADXL345 on I2C0, SDA 21 / SCL 22, address 0x53, +-16 g full resolution)
sends one radio frame per second, printed as
`tx T<seq> x<min>/<max> y<min>/<max> z<min>/<max> r<rms>*<checksum>`. The units on the conveyor and
on the fan have run for weeks. The unit on the stone crusher reboots within seconds of the crusher
starting. Its console shows:

```
Guru Meditation Error: Core  0 panic'ed (LoadStorePIFAddrError). Exception was unhandled.
Backtrace: calib_apply (main/calib.c:34) <- sampler_task (main/main.c:33) <- vPortTaskWrapper
```

The calibration code and tables have not changed since the field trial started.

Stop the reboots. Every frame must keep its format and carry all fields and the checksum,
whatever the vibration level.
