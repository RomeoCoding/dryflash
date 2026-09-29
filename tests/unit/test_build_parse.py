from pathlib import Path

from esp32_sim_mcp.build import parse_diagnostics, build_dir_for

PROJ = Path("/work/app")

GCC_LOG = """\
[1/9] Building C object esp-idf/main/CMakeFiles/__idf_main.dir/app.c.obj
FAILED: esp-idf/main/CMakeFiles/__idf_main.dir/app.c.obj
/work/app/main/app.c: In function 'app_main':
/work/app/main/app.c:12:5: error: 'undeclared_var' undeclared (first use in this function)
   12 |     undeclared_var = 3;
      |     ^~~~~~~~~~~~~~
/work/app/main/app.c:12:5: note: each undeclared identifier is reported only once for each function it appears in
/work/app/main/app.c:20:9: warning: unused variable 'x' [-Wunused-variable]
/work/app/main/app.c:12:5: error: 'undeclared_var' undeclared (first use in this function)
/opt/esp/idf/components/esp_common/include/esp_err.h:5:1: warning: something in IDF
ninja: build stopped: subcommand failed.
"""

LD_LOG = """\
/opt/esp/tools/xtensa-esp-elf/bin/../lib/gcc/xtensa-esp-elf/15.1.0/../../../../xtensa-esp-elf/bin/ld: esp-idf/main/libmain.a(app.c.obj):(.literal.app_main+0x4): undefined reference to `missing_fn'
/opt/esp/tools/xtensa-esp-elf/bin/ld: esp-idf/main/libmain.a(app.c.obj): in function `app_main':
/work/app/main/app.c:7:(.text.app_main+0x9): undefined reference to `missing_fn'
collect2: error: ld returned 1 exit status
"""

CMAKE_LOG = """\
CMake Error at main/CMakeLists.txt:1 (idf_component_register):
  idf_component_register Unknown argument: SRSC

-- Configuring incomplete, errors occurred!
"""

OVERFLOW_LOG = """\
/opt/esp/tools/xtensa-esp-elf/bin/ld: app.elf section `.dram0.bss' will not fit in region `dram0_0_seg'
/opt/esp/tools/xtensa-esp-elf/bin/ld: region `dram0_0_seg' overflowed by 51234 bytes
collect2: error: ld returned 1 exit status
"""


def test_gcc_errors_are_relative_deduped_and_errors_first():
    d = parse_diagnostics(GCC_LOG, PROJ)
    errors = [x for x in d if x.severity == "error"]
    assert len(errors) == 1
    e = errors[0]
    assert (e.file, e.line, e.column) == ("main/app.c", 12, 5)
    assert "undeclared_var" in e.message
    assert d[0].severity == "error"
    warn = [x for x in d if x.severity == "warning"]
    assert ("main/app.c", 20) in [(w.file, w.line) for w in warn]
    # Diagnostics from outside the project are kept but not relativized.
    assert any(w.file.startswith("/opt/esp/idf") for w in warn)
    assert not any(x.severity == "note" for x in d)


def test_linker_undefined_reference():
    d = parse_diagnostics(LD_LOG, PROJ)
    und = [x for x in d if "undefined reference to `missing_fn'" in x.message]
    assert und and und[0].severity == "error"
    assert any(x.file == "main/app.c" and x.line == 7 for x in und)


def test_cmake_error():
    d = parse_diagnostics(CMAKE_LOG, PROJ)
    assert d[0].severity == "error"
    assert (d[0].file, d[0].line) == ("main/CMakeLists.txt", 1)
    assert "Unknown argument: SRSC" in d[0].message


def test_memory_region_overflow():
    d = parse_diagnostics(OVERFLOW_LOG, PROJ)
    assert any("dram0_0_seg' overflowed by 51234 bytes" in x.message and x.severity == "error" for x in d)


def test_build_dir_is_stable_per_project_and_target(tmp_path):
    a = build_dir_for(Path("/work/app"), "esp32", root=tmp_path)
    assert a == build_dir_for(Path("/work/app"), "esp32", root=tmp_path)
    assert a != build_dir_for(Path("/work/app"), "esp32c3", root=tmp_path)
    assert a != build_dir_for(Path("/work/other"), "esp32", root=tmp_path)
    assert a.parent == tmp_path and "app" in a.name
