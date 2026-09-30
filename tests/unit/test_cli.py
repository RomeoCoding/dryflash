import json
from pathlib import Path

from esp32_sim_mcp.cli import main
from esp32_sim_mcp.testrun import resolve_scenario


def test_resolve_scenario_prefers_the_project_dir(tmp_path):
    (tmp_path / "s.yaml").write_text("x")
    assert resolve_scenario(tmp_path, "s.yaml") == tmp_path / "s.yaml"
    assert resolve_scenario(tmp_path, str(tmp_path / "s.yaml")) == tmp_path / "s.yaml"


def test_test_run_reports_bad_scenarios_as_json(tmp_path, capsys):
    (tmp_path / "bad.yaml").write_text("name: x\nsteps: []\n")
    code = main(["test-run", str(tmp_path), "bad.yaml", "--no-build"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["passed"] is False and "steps" in out["reason"]


def test_missing_scenario_file(tmp_path, capsys):
    code = main(["test-run", str(tmp_path), "nope.yaml", "--no-build"])
    assert code == 2 and "FileNotFoundError" in json.loads(capsys.readouterr().out)["reason"]
