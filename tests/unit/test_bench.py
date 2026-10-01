"""The benchmark tasks are well-formed and verify.py keeps earlier results. QEMU-free."""

import importlib.util
from pathlib import Path

import pytest

from dryflash.scenario import load_scenario
from dryflash.sensors.models import make_model

BENCH = Path(__file__).resolve().parents[2] / "bench"
TASKS = sorted(p.name for p in BENCH.iterdir() if (p / "app" / "CMakeLists.txt").exists())


def _load(name):
    spec = importlib.util.spec_from_file_location(f"bench_{name}", BENCH / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _verify_module():
    return _load("verify")


def test_agent_env_never_carries_an_api_key():
    # Agent runs must bill the operator's subscription login, never an API key that happens to be set.
    harness = _load("harness")
    env = harness.agent_env({"PATH": "/bin", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t"}, None)
    assert env == {"PATH": "/bin"}
    assert harness.agent_env({"PATH": "/bin"}, "/cfg")["CLAUDE_CONFIG_DIR"] == "/cfg"


@pytest.mark.parametrize("agent,stderr,expected", [
    ({"is_error": True, "result": "Claude AI usage limit reached|1759300000"}, "", True),
    ({"is_error": True, "result": "5-hour limit reached ∙ resets 3pm"}, "", True),
    ({}, "API Error: 429 rate_limit_error", True),
    ({}, "API Error: 529 Overloaded", True),
    # a finished run that merely talks about rates is not a limit
    ({"is_error": False, "result": "fixed the rate limit check in the alarm"}, "", False),
    ({"is_error": True, "result": "Reached max turns (60)"}, "", False),
])
def test_cut_off_detection(agent, stderr, expected):
    assert _load("harness").cut_off(agent, stderr) is expected


def test_there_are_tasks():
    assert len(TASKS) >= 15


@pytest.mark.parametrize("task", TASKS)
def test_task_layout(task):
    d = BENCH / task
    for f in ("TASK.md", "reference.patch", "hidden/scenario.yaml", "app/main/CMakeLists.txt"):
        assert (d / f).is_file(), f"{task}: {f} missing"
    patch = (d / "reference.patch").read_text()
    assert patch.startswith("diff ") and "\n--- a/" in patch and "\n+++ b/" in patch


@pytest.mark.parametrize("task", TASKS)
def test_hidden_scenario_and_sensors_are_valid(task):
    scenario = load_scenario(BENCH / task / "hidden" / "scenario.yaml")
    # The harness runs the scenario against the agent's copy of app/, so CSV paths resolve there.
    for spec in scenario.sensors:
        make_model(spec, BENCH / task / "app")


def test_merge_keeps_apps_that_were_not_rerun():
    verify = _verify_module()
    old = {"generated": "then", "results": [{"app": "a", "ok": True}, {"app": "b", "ok": True}]}
    merged = verify.merge_results(old, [{"app": "b", "ok": False}, {"app": "c", "ok": True}], "now")
    assert merged["generated"] == "now"
    assert merged["results"] == [{"app": "a", "ok": True}, {"app": "b", "ok": False}, {"app": "c", "ok": True}]


def test_merge_without_earlier_results():
    verify = _verify_module()
    assert verify.merge_results(None, [{"app": "x", "ok": True}], "now") == \
        {"generated": "now", "results": [{"app": "x", "ok": True}]}
