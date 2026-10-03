"""Sensor injection end to end. Needs the sensors image (patched QEMU): pytest -m sensors."""

import asyncio
import re

import pytest
from mcp.client import Client

from dryflash.server import create_server

from .conftest import REPO

pytestmark = [pytest.mark.sensors, pytest.mark.anyio]

VIB = REPO / "examples" / "vibration_monitor"
ADC = REPO / "tests" / "firmware" / "adc_probe"
MPU = REPO / "tests" / "firmware" / "mpu_probe"
ADS = {"model": "ads1115", "name": "adc", "address": 0x49, "rate_hz": 200,
       "waveform": {"ain0": 1.5, "ain1": 0.5, "ain2": 0.0, "ain3": 3.0}}


async def call(c, name, **args):
    r = await c.call_tool(name, args)
    assert not r.is_error, r.content[0].text
    return r.structured_content


def upto(text, pattern):
    m = re.search(pattern, text)
    assert m, f"{pattern!r} not in transcript"
    return text[:m.end()]


async def test_vibration_monitor_reports_injected_rms_and_is_deterministic():
    async with Client(create_server()) as c:
        runs = [await call(c, "test_run", project_dir=str(VIB), scenario_file="scenario.yaml") for _ in range(2)]
    for r in runs:
        assert r["passed"], {k: v for k, v in r.items() if k != "transcript"}
    logs = [upto(r["transcript"], r"block 6 [^\n]*\n") for r in runs]
    assert logs[0] == logs[1], "two deterministic runs must give byte-identical UART output"
    assert "block 5" in logs[0]


async def test_ads1115_mux_pga_and_registers():
    async with Client(create_server()) as c:
        s = await call(c, "emu_start", project_dir=str(ADC), sensors=[ADS], deterministic=True)
        sid = s["session_id"]
        try:
            assert (await call(c, "uart_expect", session_id=sid, pattern=r"ain3 pga2.048[^\n]*\n",
                               timeout_s=60))["matched"]
            text = (await call(c, "uart_read", session_id=sid, cursor=0, max_bytes=65536))["text"]
            assert "config at reset: 0x8583" in text
            assert "lo_thresh 0x8000 hi_thresh 0x7fff" in text
            assert "ain0 pga4.096 code=12000 v=1.5000" in text
            assert "ain0 pga2.048 code=24000 v=1.5000" in text
            assert "ain0-ain1 pga2.048 code=16000 v=1.0000" in text
            assert "ain3 pga2.048 code=32767" in text            # 3.0 V clips at +-2.048 V
            # The loop's first conversion reconfigures the ADC to AIN0 at +-4.096 V.
            assert (await call(c, "uart_expect", session_id=sid, pattern=r"tick 1 ", timeout_s=30))["matched"]
            status = await call(c, "emu_status", session_id=sid)
            cfg = status["sensors"][0]["guest_config"]
            assert cfg["input"] == "ain0-gnd" and cfg["full_scale_v"] == 4.096
        finally:
            await call(c, "emu_stop", session_id=sid)


async def test_exact_run_for_and_sensor_set_while_paused():
    async with Client(create_server()) as c:
        s = await call(c, "emu_start", project_dir=str(ADC), sensors=[ADS], deterministic=True)
        sid = s["session_id"]
        try:
            r = await call(c, "emu_run_for", session_id=sid, virtual_ms=1500)
            assert r["exact"] is True and r["state"] == "paused"
            t1 = r["virtual_time_ns"]
            r2 = await call(c, "emu_run_for", session_id=sid, virtual_ms=250)
            assert r2["virtual_time_ns"] - t1 == 250_000_000
            before = (await call(c, "uart_read", session_id=sid, cursor=0, max_bytes=1))["cursor"]
            ticks_before = len(re.findall(r"tick \d+ ain0=1\.5000",
                                          (await call(c, "uart_read", session_id=sid, max_bytes=65536))["text"]))
            assert ticks_before >= 5
            st = await call(c, "sensor_set", session_id=sid, sensor="adc", values={"ain0": 2.25})
            assert st["applies_from_ms"] == pytest.approx(r2["virtual_time_ns"] / 1e6)  # "now" while paused
            await call(c, "emu_continue", session_id=sid)
            m = await call(c, "uart_expect", session_id=sid, pattern=r"tick \d+ ain0=2\.2500", timeout_s=30,
                           cursor=before)
            assert m["matched"]
        finally:
            await call(c, "emu_stop", session_id=sid)


async def test_csv_stream(tmp_path):
    async with Client(create_server()) as c:
        s = await call(c, "emu_start", project_dir=str(ADC), sensors=[ADS], deterministic=True)
        sid = s["session_id"]
        try:
            await call(c, "emu_run_for", session_id=sid, virtual_ms=1000)
            csv = ADC / "ramp.csv"
            r = await call(c, "sensor_stream", session_id=sid, sensor="adc",
                           waveform={"ain0": {"type": "csv", "path": str(csv), "column": "volts", "loop": True}})
            assert r["channels"] == ["ain0"]
            await call(c, "emu_continue", session_id=sid)
            seen = set()
            cursor = 0
            for _ in range(12):
                m = await call(c, "uart_expect", session_id=sid, pattern=r"tick \d+ ain0=([0-9.]+)",
                               timeout_s=30, cursor=cursor)
                cursor = m["cursor"]
                seen.add(m["groups"][0])
            assert {"0.5000", "1.0000", "2.0000"} & seen, seen
        finally:
            await call(c, "emu_stop", session_id=sid)


async def test_reset_reconnects_sensors():
    async with Client(create_server()) as c:
        s = await call(c, "emu_start", project_dir=str(VIB), sensors=[
            {"model": "adxl345", "name": "accel", "waveform": {"z": 1.0}}])
        sid = s["session_id"]
        try:
            assert (await call(c, "uart_expect", session_id=sid, pattern="DEVID=0xe5", timeout_s=60))["matched"]
            r = await call(c, "emu_reset", session_id=sid)
            m = await call(c, "uart_expect", session_id=sid, pattern=r"block 1 [^\n]*mean_z=(0\.99\d|1\.00\d)",
                           timeout_s=60, cursor=r["uart_cursor_at_reset"])
            assert m["matched"], m
        finally:
            await call(c, "emu_stop", session_id=sid)


async def test_sensor_errors_are_reported():
    async with Client(create_server()) as c:
        r = await c.call_tool("emu_start", {"project_dir": str(ADC), "sensors": [
            {"model": "ads1115", "name": "adc", "address": 0x48}]})
        assert r.is_error and "tmp105" in r.content[0].text
        r = await c.call_tool("emu_start", {"project_dir": str(ADC), "target": "esp32c3",
                                            "sensors": [ADS]})
        assert r.is_error and "only on esp32" in r.content[0].text


async def test_mpu6050_ranges_sleep_reset_and_determinism():
    async with Client(create_server()) as c:
        runs = [await call(c, "test_run", project_dir=str(MPU), scenario_file="scenario.yaml") for _ in range(2)]
    for r in runs:
        assert r["passed"], {k: v for k, v in r.items() if k != "transcript"}
    logs = [upto(r["transcript"], r"tick 12 [^\n]*\n") for r in runs]
    assert logs[0] == logs[1], "two deterministic runs must give byte-identical UART output"
    assert len(re.findall(r"^range afs\d fs\d ", logs[0], re.M)) == 16


IO = REPO / "tests" / "firmware" / "io_probe"


async def test_gpio_and_spi_devices_scenario_is_deterministic():
    async with Client(create_server()) as c:
        runs = [await call(c, "test_run", project_dir=str(IO), scenario_file="scenario.yaml") for _ in range(2)]
    for r in runs:
        assert r["passed"], {k: v for k, v in r.items() if k != "transcript"}
    logs = [upto(r["transcript"], r"fault=1 oc=1[^\n]*\n") for r in runs]
    assert logs[0] == logs[1], "two deterministic runs must give byte-identical UART output"
    gpio_step = next(s for s in runs[0]["steps"] if s["action"] == "expect_gpio")
    assert gpio_step["result"]["freq_hz"] == pytest.approx(2.0, abs=0.01)


async def test_gpio_tools_trace_read_and_pulse():
    tc = {"model": "max31855", "name": "tc", "bus": "spi3", "cs": 0, "waveform": {"tc_c": 20.0}}
    k = {"model": "max6675", "name": "k", "bus": "spi2", "cs": 0, "cs_gpio": 15}
    async with Client(create_server()) as c:
        s = await call(c, "emu_start", project_dir=str(IO), deterministic=True, sensors=[tc, k],
                       gpio=[{"pin": 27, "default": 1}])
        sid = s["session_id"]
        try:
            assert s["gpio"]["declared_inputs"] == [{"pin": 15, "default": 1}, {"pin": 27, "default": 1}]
            assert (await call(c, "uart_expect", session_id=sid, pattern="io_probe ready", timeout_s=60))["matched"]
            await call(c, "emu_run_for", session_id=sid, virtual_ms=1700)
            tr = await call(c, "gpio_trace", session_id=sid, pin=25)
            rising = [e["t_ms"] for e in tr["edges"] if e["level"] == 1]
            # the first rising edge is the blink task starting; after it the LED toggles every 250 ms
            assert len(rising) >= 4 and all(abs(b - a - 500.0) < 1.0 for a, b in zip(rising[1:], rising[2:]))
            assert (await call(c, "gpio_read", session_id=sid, pin=27))["level"] == 1
            now = tr["virtual_ms_now"]
            p = await call(c, "gpio_pulse", session_id=sid, pin=27, width_ms=20, at_ms=now + 100)
            assert p["deterministic"] is True and p["events"][0]["level"] == 0
            await call(c, "emu_continue", session_id=sid)
            assert (await call(c, "uart_expect", session_id=sid, pattern=r"button pressed at \d+ ms, level 0",
                               timeout_s=30))["matched"]
            bad = await c.call_tool("gpio_set", {"session_id": sid, "pin": 24, "level": 1})
            assert bad.is_error and "not an ESP32 GPIO pad" in bad.content[0].text
        finally:
            await call(c, "emu_stop", session_id=sid)


VERUS = REPO / "examples" / "verus_pod"


async def test_verus_pod_scenario_twice_byte_identical():
    async with Client(create_server()) as c:
        runs = [await call(c, "test_run", project_dir=str(VERUS), scenario_file="scenario.yaml") for _ in range(2)]
    for r in runs:
        assert r["passed"], {k: v for k, v in r.items() if k != "transcript"}
    logs = [r["transcript"] for r in runs]
    assert logs[0] == logs[1], "two deterministic runs must give byte-identical UART output"
    code = re.search(r'"code":"(\d{6})"', logs[0]).group(1)
    shown = runs[0]["steps"][-1]["text"]
    assert shown == ["PAIR", code], "the OLED must show the code the firmware printed"


async def test_verus_pod_through_the_mcp_tools_and_the_uart_tee():
    import json

    import yaml
    scn = yaml.safe_load((VERUS / "scenario.yaml").read_text())
    async with Client(create_server()) as c:
        s = await call(c, "emu_start", project_dir=str(VERUS), deterministic=True, sensors=scn["sensors"],
                       gpio=scn["gpio"], uart_tcp_port=47321)
        sid = s["session_id"]
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", 47321), 10)
            line = b""
            while b'"type":"features"' not in line:  # what a host app on socket://host:47321 reads
                line = await asyncio.wait_for(reader.readline(), 120)
            frame = json.loads(line)
            assert set(frame["features"]) == {"vib_rms_g", "hall_ac_mv", "temp_c"}
            assert (await call(c, "emu_status", session_id=sid))["uart_tcp_clients"] == 1
            writer.write(b"ping\n")  # host-to-pod bytes reach the guest's RX without disturbing it
            await writer.drain()
            await call(c, "sensor_set", session_id=sid, sensor="tc", values={"fault": "open"})
            assert (await call(c, "uart_expect", session_id=sid, pattern='"event":"detached","id":"tmp_max31855_cs5"',
                               timeout_s=60))["matched"]
            await call(c, "gpio_pulse", session_id=sid, pin=27, width_ms=80)
            m = await call(c, "uart_expect", session_id=sid, pattern=r'"code":"(\d{6})"', timeout_s=60)
            await call(c, "emu_run_for", session_id=sid, virtual_ms=300)  # the code is printed before the flush
            snap = await call(c, "display_snapshot", session_id=sid, sensor="oled", png=True)
            assert snap["on"] and snap["text"] == ["PAIR", m["groups"][0]] and snap["png"].endswith(".png")
            await call(c, "emu_run_for", session_id=sid, virtual_ms=1000)
            edges = (await call(c, "gpio_trace", session_id=sid, pin=25))["edges"]
            await call(c, "emu_continue", session_id=sid)
            assert len(edges) >= 4
            writer.close()
        finally:
            await call(c, "emu_stop", session_id=sid)
