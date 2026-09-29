"""Integration fixtures: real ESP-IDF builds and QEMU sessions. Run inside the test image."""

import asyncio
from pathlib import Path

import pytest

from esp32_sim_mcp.build import build_project

REPO = Path(__file__).resolve().parents[2]
HELLO = REPO / "examples" / "hello_world"
CRASHLAB = REPO / "tests" / "firmware" / "crashlab"

_builds: dict = {}


def built(project: Path, target: str = "esp32"):
    key = (project, target)
    if key not in _builds:
        res = asyncio.run(build_project(project, target))
        assert res.ok, res.to_dict()
        _builds[key] = res
    return _builds[key]


@pytest.fixture(scope="session")
def hello_build():
    return built(HELLO)


@pytest.fixture(scope="session")
def crashlab_build():
    return built(CRASHLAB)
