"""Run a prebuilt Arduino image (merged 4 MB flash + ELF) in dryflash with the Verus sensors."""
import asyncio
import sys
from pathlib import Path

from dryflash.runner import run_scenario
from dryflash.scenario import parse_scenario
from dryflash.session import SessionConfig, SessionManager

SCENARIO = """
name: arduino compatibility check
target: esp32
timeout_s: 120
emulator: {deterministic: true}
gpio: [{pin: 27, default: 1}]
sensors:
  - {model: mpu6050, name: imu, waveform: {x: 0.25, z: 1.0}}
  - {model: ads1115, name: adc, address: 0x49, waveform: {ain0: 1.65}}
  - {model: max31855, name: tc, bus: spi3, cs: 0, cs_gpio: %s, waveform: {tc_c: 31.25, cj_c: 24}}
steps:
  - expect: 'ARD max31855 begin'
    timeout_s: 60
  - expect: 'ARD ax=[^\\n]*'
  - expect: 'ARD ax=[^\\n]*'
  - expect_gpio: {pin: 25, within_ms: 2000, min_edges: 3}
  - gpio_set: {pin: 27, level: 0}
  - expect: 'ARD ax=[^\\n]*btn=0'
    timeout_s: 20
"""


async def main(image: str, elf: str, cs_gpio: str):
    mgr = SessionManager()
    sc = parse_scenario(SCENARIO % cs_gpio)
    s = await mgr.start(SessionConfig(target="esp32", flash_image=Path(image), elf=Path(elf),
                                      deterministic=True, sensors=sc.sensors, gpio=sc.gpio))
    try:
        r = await run_scenario(s, sc, transcript_bytes=4000)
    finally:
        await mgr.stop(s.id)
    print("passed", r["passed"], r.get("reason"))
    for st in r["steps"]:
        print(" ", st["index"], st["action"], st["passed"], st.get("error") or st.get("match") or st.get("result", ""))
    print(r["transcript"][-2500:])


asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
