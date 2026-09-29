import pytest

from esp32_sim_mcp.scenario import ScenarioError, load_scenario, parse_scenario

MINIMAL = """
name: hello
steps:
  - expect: "Hello world!"
"""


def test_minimal_defaults():
    s = parse_scenario(MINIMAL)
    assert s.name == "hello"
    assert s.target == "esp32"
    assert s.emulator.deterministic is True
    assert s.steps[0].action == "expect"
    assert s.steps[0].timeout_s == 10
    assert any("Guru Meditation" in p for p in s.fail_on)


def test_full_example():
    s = parse_scenario("""
name: sensor check
description: accelerometer RMS must track the injected sine
target: esp32
timeout_s: 90
emulator: {deterministic: true, icount_shift: 2, watchdogs: false, qemu_args: ["-d", "guest_errors"]}
fail_on: ["PANIC"]
steps:
  - expect: 'rms=(\\d+\\.\\d+)'
    timeout_s: 20
    value_range: [0.69, 0.72]
  - write: "reset\\n"
  - run_for_ms: 250
  - expect_not: "overflow"
    within_s: 2
""")
    assert s.emulator.icount_shift == 2 and s.emulator.watchdogs is False
    assert s.fail_on == ["PANIC"]
    assert [st.action for st in s.steps] == ["expect", "write", "run_for_ms", "expect_not"]
    assert s.steps[0].value_range == (0.69, 0.72)
    assert s.steps[1].write == "reset\n"


def test_step_must_have_exactly_one_action():
    with pytest.raises(ScenarioError, match="exactly one"):
        parse_scenario("name: x\nsteps:\n  - {expect: a, write: b}\n")
    with pytest.raises(ScenarioError, match="exactly one"):
        parse_scenario("name: x\nsteps:\n  - {timeout_s: 3}\n")


def test_invalid_regex_is_reported_with_step_index():
    with pytest.raises(ScenarioError, match=r"steps\.0.*regex"):
        parse_scenario("name: x\nsteps:\n  - expect: '(unclosed'\n")


def test_unknown_target_and_unknown_keys():
    with pytest.raises(ScenarioError, match="esp8266"):
        parse_scenario("name: x\ntarget: esp8266\nsteps: [{expect: a}]\n")
    with pytest.raises(ScenarioError, match="expct"):
        parse_scenario("name: x\nsteps:\n  - expct: a\n")


def test_value_range_needs_a_capture_group():
    with pytest.raises(ScenarioError, match="capture group"):
        parse_scenario("name: x\nsteps:\n  - {expect: 'rms=1', value_range: [0, 1]}\n")


def test_sensors_only_on_esp32():
    with pytest.raises(ScenarioError, match="only on esp32"):
        parse_scenario("name: x\ntarget: esp32c3\nsensors: [{model: adxl345, name: a}]\nsteps: [{expect: a}]\n")


def test_load_from_file(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(MINIMAL)
    assert load_scenario(p).name == "hello"
    with pytest.raises(ScenarioError, match="not valid YAML"):
        parse_scenario("name: [unclosed")
