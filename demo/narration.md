# dryflash demo: narration

<!-- One section per demo step, keyed by the step id in run_demo.py (STEP_IDS). With
     `run_demo.py --narration`, each section is shown as a caption when its step starts and held
     for its reading time (150 words per minute), so a voiceover read at that pace stays in sync.
     The cue times of the actual run are written to demo/cues.srt. Keep the claims true to what
     the run shows; the numbers quoted here come from demo/transcript.md. -->

## intro
This is dryflash, an MCP server that lets an AI agent build ESP32 firmware, run it in Espressif's
QEMU, talk to its serial console, decode crashes and feed it sensor data. There is no board on
this desk. Everything you see is a real tool call from an MCP client.

## crash
First bug: a configuration shell that reboots when an operator forgets a value.

## crash.build
The agent builds the project with ESP-IDF inside the container.

## crash.start
Then it starts the firmware in the emulator.

## crash.boot
It waits for the shell's ready message on the emulated UART.

## crash.type
Now it types what the operator typed: "set name", with no value.

## crash.panic
The expected reply never comes. The session has ended: the firmware crashed and the chip reset.

## crash.decode
decode_panic turns the Guru Meditation dump into a cause: a NULL pointer read in apply_setting,
main.c line 21, with a symbolised backtrace.

## crash.stop
The agent stops the session.

## crash.fix
The fix checks for the missing argument. In this demo, the benchmark's reference patch stands in
for the edit an agent would make.

## crash.test
A scenario test replays the operator's commands, including both mistakes, against the fixed
build. It passes.

## sensor
Second bug: no crash at all. A voltmeter reads an ADS1115 analog-to-digital converter over I2C.

## sensor.fail
The test injects 1.234 volts on input zero and, at exactly three seconds of virtual time,
changes it to 2.5. The firmware reports minus 3.579 volts. The test fails.

## sensor.fix
The converter sends its result most significant byte first; the firmware assembled it the other
way round. The fix swaps the bytes.

## sensor.pass
The same deterministic test now passes: 1.234 volts, then 2.5.

## outro
Two bugs, found and fixed without hardware: one from a decoded crash, one from injected sensor
data. Both are from dryflash's benchmark. The benchmark shows the tool working; it does not yet
show agents doing better with it than without it, and the README says so.
