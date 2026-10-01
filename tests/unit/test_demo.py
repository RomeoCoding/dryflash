"""demo/run_demo.py presentation helpers (pacing, narration, cues). QEMU-free: nothing here starts the server."""

import importlib.util
import re
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[2] / "demo"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("run_demo", DEMO / "run_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_narration_joins_paragraph_lines_and_skips_comments(demo):
    text = "# Narration\n<!-- note for the presenter -->\n\n## intro\nFirst line\nsecond line.\n\n## crash.build\nBuild it.\n"
    assert demo.parse_narration(text) == {"intro": "First line second line.", "crash.build": "Build it."}


def test_parse_narration_rejects_duplicate_ids(demo):
    with pytest.raises(ValueError, match="intro"):
        demo.parse_narration("## intro\na\n## intro\nb\n")


def test_shipped_narration_covers_exactly_the_demo_steps(demo):
    narration = demo.parse_narration((DEMO / "narration.md").read_text(encoding="utf-8"))
    assert set(narration) == set(demo.STEP_IDS)
    assert all(narration.values())


def test_step_ids_match_the_cues_in_the_script_in_order(demo):
    source = (DEMO / "run_demo.py").read_text(encoding="utf-8")
    assert tuple(re.findall(r'cue\("([a-z_.]+)"\)', source)) == demo.STEP_IDS


def test_reading_time_has_a_floor_and_grows_with_words(demo):
    assert demo.reading_time("two words") == 2.0
    assert demo.reading_time(" ".join(["w"] * 25)) == pytest.approx(10.0)  # 2.5 words per second


def test_srt_format(demo):
    srt = demo.format_srt([(1.5, 4.0, "Hello"), (65.25, 70.0, "Two\nlines")])
    assert srt == ("1\n00:00:01,500 --> 00:00:04,000\nHello\n\n"
                   "2\n00:01:05,250 --> 00:01:10,000\nTwo\nlines\n\n")


@pytest.mark.parametrize("arg,env,expected", [
    (None, {}, 1.0),
    (None, {"DEMO_FAST": "1"}, 0.0),
    (None, {"DEMO_PACE": "1.5"}, 1.5),
    (0.5, {"DEMO_PACE": "2"}, 0.5),
])
def test_pace_resolution(demo, arg, env, expected):
    assert demo.resolve_pace(arg, env) == expected


def test_hold_scales_with_pace(demo, monkeypatch):
    slept = []
    monkeypatch.setattr(demo.time, "sleep", slept.append)
    demo.Presenter(pace=0.0, color=False).hold(5)
    demo.Presenter(pace=2.0, color=False).hold(1.5)
    assert slept == [3.0]


def test_plain_rendering_has_no_escape_codes(demo):
    p = demo.Presenter(pace=0.0, color=False)
    assert "\x1b" not in p.render_json({"passed": True, "reason": None})
    assert "\x1b" not in p.banner("1. A crash, decoded")


def test_colour_marks_pass_and_fail(demo):
    p = demo.Presenter(pace=0.0, color=True)
    assert "\x1b[32m" in p.render_json({"passed": True})   # green
    assert "\x1b[31m" in p.render_json({"passed": False})  # red


def test_subtitles_split_long_text_into_two_line_cues_timed_by_words(demo):
    text = ("This is dryflash, an MCP server for ESP32 firmware. There is no board on this desk. "
            "Everything you see is a real tool call.")
    subs = demo.subtitles([(0.0, 10.0, text)], line_chars=42)
    assert len(subs) > 1
    for _, _, s in subs:
        assert len(s.splitlines()) <= 2 and all(len(line) <= 42 for line in s.splitlines())
    assert " ".join(" ".join(s.split()) for _, _, s in subs) == " ".join(text.split())
    assert subs[0][0] == 0.0 and subs[-1][1] == pytest.approx(10.0)
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(subs, subs[1:]))  # back to back


def test_subtitles_never_overlap_the_next_cue(demo):
    subs = demo.subtitles([(0.0, 20.0, "First cue."), (5.0, 7.0, "Second cue.")])
    assert subs == [(0.0, 5.0, "First cue."), (5.0, 7.0, "Second cue.")]


def test_screen_view_condenses_long_fields_and_keeps_the_rest(demo):
    body = {
        "passed": True,
        "steps": [
            {"index": 0, "action": "expect", "pattern": "ain0=([-0-9.]+) V", "match": "ain0=1.234 V", "passed": True},
            {"index": 1, "action": "sensor_set", "result": {"sensor": "adc", "applies_from_ms": 3000.0},
             "passed": True},
            {"index": 2, "action": "write", "passed": True},
            {"index": 3, "action": "expect", "pattern": "x", "passed": False},
        ],
        "sizes": {"app_bin_bytes": 143456, "app_partition_free_pct": 86.3, "memory": {"IRAM": {"used": 1}}},
        "backtrace": [{"pc": "0x1", "function": "apply_setting", "file": "main/main.c", "line": 21},
                      {"pc": "0x2", "function": None, "file": None, "line": None}],
    }
    view = demo.screen_view(body)
    assert view["passed"] is True
    assert view["steps"] == ["✓ expect → ain0=1.234 V", "✓ sensor_set adc from 3000 ms", "✓ write",
                             "✗ expect x"]
    assert view["sizes"] == {"app_bin_bytes": 143456, "app_partition_free_pct": 86.3}
    assert view["backtrace"] == ["apply_setting (main/main.c:21)", "0x2"]
    assert body["steps"][0]["match"] == "ain0=1.234 V"  # the transcript's copy is untouched


def test_cues_are_recorded_relative_to_the_start(demo, monkeypatch):
    clock = iter([100.0, 103.0])
    monkeypatch.setattr(demo.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(demo.time, "sleep", lambda s: None)
    p = demo.Presenter(pace=1.0, color=False, narration={"intro": "Hello there"})  # start = 100.0
    p.narrate("intro")                                                              # at 103.0
    assert p.cues == [(3.0, 5.0, "Hello there")]
