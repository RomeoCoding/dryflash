"""The benchmark tasks are well-formed and verify.py keeps earlier results. QEMU-free."""

import importlib.util
from pathlib import Path

import pytest

from dryflash.scenario import load_scenario
from dryflash.sensors.models import make_model

BENCH = Path(__file__).resolve().parents[2] / "bench"
TASKS = sorted(p.name for p in BENCH.iterdir() if (p / "app" / "CMakeLists.txt").exists())


def _verify_module():
    spec = importlib.util.spec_from_file_location("bench_verify", BENCH / "verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
