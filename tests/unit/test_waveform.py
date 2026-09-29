import math
import statistics

import pytest

from esp32_sim_mcp.sensors.waveform import WaveformError, parse_waveform


def test_number_and_constant():
    assert parse_waveform(1.5).value(3.0) == 1.5
    assert parse_waveform({"type": "constant", "value": -2}).value(0) == -2


def test_sine():
    w = parse_waveform({"type": "sine", "freq_hz": 10, "amplitude": 2.0, "offset": 1.0})
    assert w.value(0) == pytest.approx(1.0)
    assert w.value(0.025) == pytest.approx(3.0)  # quarter period
    w2 = parse_waveform({"type": "sine", "freq_hz": 10, "amplitude": 1, "phase_deg": 90})
    assert w2.value(0) == pytest.approx(1.0)


def test_list_is_a_sum():
    w = parse_waveform([1.0, {"type": "sine", "freq_hz": 5, "amplitude": 0.5}])
    assert w.value(0.05) == pytest.approx(1.5)


def test_noise_is_deterministic_per_time_and_seed():
    a = parse_waveform({"type": "noise", "std": 0.1, "seed": 7})
    b = parse_waveform({"type": "noise", "std": 0.1, "seed": 7})
    c = parse_waveform({"type": "noise", "std": 0.1, "seed": 8})
    ts = [i / 1000 for i in range(4000)]
    va = [a.value(t) for t in ts]
    assert va == [b.value(t) for t in ts]
    assert va != [c.value(t) for t in ts]
    assert statistics.pstdev(va) == pytest.approx(0.1, rel=0.1)
    # Same instant, evaluated again later (e.g. a re-sent chunk): same value.
    assert a.value(1.234) == a.value(1.234)


def test_step():
    w = parse_waveform({"type": "step", "steps": [[0, 0.0], [0.5, 1.0], [1.0, -1.0]]})
    assert [w.value(t) for t in (0, 0.49, 0.5, 0.99, 5)] == [0.0, 0.0, 1.0, 1.0, -1.0]


def test_rotation_line_at_1x_with_harmonics():
    w = parse_waveform({"type": "rotation", "rpm": 1500, "amplitude": 0.3, "harmonics": [[2, 0.1]]})
    f1 = 1500 / 60
    t = 0.0123
    expected = 0.3 * math.sin(2 * math.pi * f1 * t) + 0.1 * math.sin(2 * math.pi * 2 * f1 * t)
    assert w.value(t) == pytest.approx(expected)


def test_csv_interpolates_and_loops(tmp_path):
    p = tmp_path / "rec.csv"
    p.write_text("t,x,y\n0,0,10\n0.1,1,20\n0.2,0,30\n")
    w = parse_waveform({"type": "csv", "path": str(p), "column": "x"})
    assert w.value(0.05) == pytest.approx(0.5)
    assert w.value(0.2) == pytest.approx(0.0)
    assert w.value(0.3) == pytest.approx(0.0)  # holds the last sample without loop
    wl = parse_waveform({"type": "csv", "path": str(p), "column": "y", "loop": True})
    assert wl.value(0.25) == pytest.approx(15.0)  # 0.25 wraps to 0.05 of the 0.2 s record
    wi = parse_waveform({"type": "csv", "path": str(p), "column": 2, "time_column": 0})
    assert wi.value(0.1) == pytest.approx(20.0)


def test_csv_time_in_ms(tmp_path):
    p = tmp_path / "rec.csv"
    p.write_text("ms,v\n0,0\n100,2\n")
    w = parse_waveform({"type": "csv", "path": str(p), "column": "v", "time_unit": "ms"})
    assert w.value(0.05) == pytest.approx(1.0)


def test_csv_relative_path_uses_base_dir(tmp_path):
    (tmp_path / "d.csv").write_text("t,v\n0,1\n1,1\n")
    assert parse_waveform({"type": "csv", "path": "d.csv", "column": "v"}, base_dir=tmp_path).value(0.5) == 1


@pytest.mark.parametrize("bad, msg", [
    ({"type": "sine"}, "freq_hz"),
    ({"type": "square", "freq_hz": 1}, "unknown waveform type"),
    ({"type": "csv", "path": "/nope.csv", "column": "x"}, "nope.csv"),
    ("abc", "number, list or mapping"),
])
def test_errors(bad, msg):
    with pytest.raises(WaveformError, match=msg):
        parse_waveform(bad)
