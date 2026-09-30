"""ESP-IDF builds: run idf.py out of tree, parse diagnostics, report sizes, make a QEMU flash image."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .targets import get_target

BUILD_ROOT = Path(os.environ.get("DRYFLASH_BUILD_ROOT", "/tmp/dryflash/builds"))

_GCC = re.compile(
    r"^(?P<file>[^\s:][^:\n]*?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?P<sev>fatal error|error|warning|note):\s*(?P<msg>.+)$", re.M)
_LD_UNDEF = re.compile(
    r"^(?P<file>[^\s:][^:\n]*?):(?P<line>\d+):(?:\([^)]*\))?:?\s*(?P<msg>undefined reference to .+)$", re.M)
_LD_OTHER = re.compile(
    r"^\S*ld(?:\.exe)?: (?P<msg>.*(?:undefined reference|overflowed by|will not fit|multiple definition).*)$", re.M)
_CMAKE = re.compile(r"^CMake Error at (?P<file>[^:\n]+):(?P<line>\d+) \([^)]*\):\n(?P<body>(?:  .*\n?)+)", re.M)


@dataclass
class Diagnostic:
    severity: str  # error | warning
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None

    def key(self):
        return (self.severity, self.file, self.line, self.column, self.message)


def _rel(path: str, project_dir: Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        return path
    try:
        return p.relative_to(project_dir).as_posix()
    except ValueError:
        return path


def parse_diagnostics(log: str, project_dir: Path) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for m in _GCC.finditer(log):
        sev = m["sev"]
        if sev == "note":
            continue
        out.append(Diagnostic("error" if sev == "fatal error" else sev, m["msg"].strip(),
                              _rel(m["file"], project_dir), int(m["line"]),
                              int(m["col"]) if m["col"] else None))
    for m in _LD_UNDEF.finditer(log):
        out.append(Diagnostic("error", m["msg"].strip(), _rel(m["file"], project_dir), int(m["line"])))
    for m in _LD_OTHER.finditer(log):
        out.append(Diagnostic("error", m["msg"].strip()))
    for m in _CMAKE.finditer(log):
        body = " ".join(line.strip() for line in m["body"].splitlines() if line.strip())
        out.append(Diagnostic("error", body, _rel(m["file"], project_dir), int(m["line"])))
    seen, uniq = set(), []
    for d in out:
        if d.key() not in seen:
            seen.add(d.key())
            uniq.append(d)
    uniq.sort(key=lambda d: d.severity != "error")  # stable: errors first, log order kept
    return uniq


def build_dir_for(project_dir: Path, target: str, root: Path = BUILD_ROOT) -> Path:
    # Out-of-tree and container-local: builds on a bind-mounted Windows/macOS folder are several
    # times slower, and the user's project stays free of root-owned build output.
    digest = hashlib.sha1(str(project_dir.resolve()).encode()).hexdigest()[:10]
    return root / f"{project_dir.name}-{digest}-{target}"


@dataclass
class BuildResult:
    ok: bool
    target: str
    project_dir: str
    build_dir: str
    duration_s: float
    diagnostics: list[Diagnostic] = field(default_factory=list)
    sizes: dict = field(default_factory=dict)
    elf: str | None = None
    flash_image: str | None = None
    log_tail: str = ""

    def to_dict(self, max_diagnostics: int = 30) -> dict:
        d = asdict(self)
        errs = [x for x in self.diagnostics if x.severity == "error"]
        warns = [x for x in self.diagnostics if x.severity == "warning"]
        d["diagnostics"] = [asdict(x) for x in (errs + warns)[:max_diagnostics]]
        d["error_count"], d["warning_count"] = len(errs), len(warns)
        if self.ok:
            d.pop("log_tail")
        return d


async def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 900) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"timed out after {timeout:.0f}s: {' '.join(cmd)}"
    return proc.returncode or 0, out.decode(errors="replace")


def _idf_python() -> str:
    env = os.environ.get("IDF_PYTHON_ENV_PATH")
    return str(Path(env) / "bin" / "python") if env else "python"


async def build_project(project_dir: Path, target: str = "esp32", clean: bool = False,
                        timeout: float = 900) -> BuildResult:
    get_target(target)
    project_dir = project_dir.resolve()
    t0 = time.monotonic()
    bdir = build_dir_for(project_dir, target)
    res = BuildResult(False, target, str(project_dir), str(bdir), 0.0)
    if not (project_dir / "CMakeLists.txt").is_file():
        res.diagnostics = [Diagnostic("error", f"{project_dir} has no CMakeLists.txt; not an ESP-IDF project")]
        return res
    if clean and bdir.exists():
        shutil.rmtree(bdir)
    bdir.mkdir(parents=True, exist_ok=True)
    sdkconfig = bdir / "sdkconfig"
    if not sdkconfig.exists() and (project_dir / "sdkconfig").exists():
        shutil.copy(project_dir / "sdkconfig", sdkconfig)
    base = ["idf.py", "-C", str(project_dir), "-B", str(bdir), f"-DSDKCONFIG={sdkconfig}",
            f"-DIDF_TARGET={target}"]
    code, log = await _run(base + ["build"], timeout=timeout)
    res.duration_s = round(time.monotonic() - t0, 1)
    res.diagnostics = parse_diagnostics(log, project_dir)
    res.log_tail = log[-3000:]
    if code != 0:
        if not any(d.severity == "error" for d in res.diagnostics):
            res.diagnostics.insert(0, Diagnostic("error", f"idf.py build failed (exit {code}); see log_tail"))
        return res
    desc = json.loads((bdir / "project_description.json").read_text())
    res.elf = str(bdir / desc["app_elf"])
    res.flash_image = str(bdir / "flash_qemu.bin")
    code, mlog = await _run([_idf_python(), "-m", "esptool", "--chip", target, "merge-bin",
                             "--pad-to-size", "4MB", "-o", res.flash_image, "@flash_args"], cwd=bdir)
    if code != 0:
        res.diagnostics.insert(0, Diagnostic("error", f"esptool merge-bin failed: {mlog[-500:]}"))
        return res
    res.sizes = await _sizes(bdir, desc)
    res.ok = True
    return res


async def _sizes(bdir: Path, desc: dict) -> dict:
    sizes: dict = {}
    app_bin = bdir / desc.get("app_bin", "")
    if app_bin.is_file():
        sizes["app_bin_bytes"] = app_bin.stat().st_size
    part = await _app_partition_size(bdir)
    if part and "app_bin_bytes" in sizes:
        sizes["app_partition_bytes"] = part
        sizes["app_partition_free_pct"] = round(100 * (1 - sizes["app_bin_bytes"] / part), 1)
    map_file = bdir / desc.get("app_elf", "").replace(".elf", ".map")
    if map_file.is_file():
        code, out = await _run([_idf_python(), "-m", "esp_idf_size", "--format", "json2", str(map_file)])
        if code == 0:
            try:
                layout = json.loads(out[out.index("{"):])["layout"]
                sizes["memory"] = {
                    x["name"]: {"used": x["used"], **({"total": x["total"]} if x["total"] else {})}
                    for x in layout
                }
            except (ValueError, KeyError):
                pass
    return sizes


async def _app_partition_size(bdir: Path) -> int | None:
    table = bdir / "partition_table" / "partition-table.bin"
    tool = Path(os.environ.get("IDF_PATH", "/opt/esp/idf")) / "components/partition_table/gen_esp32part.py"
    if not table.is_file() or not tool.is_file():
        return None
    code, out = await _run([_idf_python(), str(tool), str(table)])
    if code != 0:
        return None
    for line in out.splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) >= 5 and cols[1] == "app":
            return _parse_size(cols[4])
    return None


def _parse_size(s: str) -> int:
    mult = {"K": 1024, "M": 1024 * 1024}
    return int(float(s[:-1]) * mult[s[-1]]) if s[-1] in mult else int(s, 0)
