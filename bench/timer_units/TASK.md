# Heartbeat count is way off

The heartbeat should beat every 100 ms, so the app should report about 10 beats per second of
uptime (`uptime 2 s beats=20`). The reported counts are far too high. Make the heartbeat run at
10 Hz.
