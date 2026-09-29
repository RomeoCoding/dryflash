# Decisions

One entry per non-obvious call: the decision, the alternative, and why.

## M1

- **Stock QEMU from the IDF image for the base image; patched QEMU only in the second image.**
  Alternative: always build QEMU. Why: the v6.1 image already ships the pinned
  esp_develop_9.2.2_20260417 build, and the base image stays GPL-patch-free and quick to build.
- **Patch 0001 moves the esp32 I2C controllers to sysbus-default and uses auto bus names
  (`i2c-bus.0/1`).** Alternatives: a machine property listing I2C devices, or creating devices
  from machine init. Why: it is the conventional QEMU arrangement (aspeed and others do the same),
  it's the smallest diff, it keeps `-device ...,bus=` working for any I2C slave, and the reset
  side effect can't be observed (see M1_REPORT question 2).
- **Keep the hard-wired tmp105 at 0x48; ADS1115 examples use 0x49.** Alternative: remove it or
  gate it behind a machine property. Why: removing it changes behaviour for existing users, and
  a property would add patch surface for little gain.
- **Deterministic mode = `-icount shift=3,sleep=off`.** Alternatives: shift=2 (closer to
  240 MHz, 1.8× slower in wall time), shift=5 (fast but measured non-deterministic). Why: it is
  the fastest setting that was byte-identical in 10/10 runs.
- **The QEMU build fetches meson subprojects (keycodemapdb, dtc wraps) with git at the
  revisions pinned in the tarball.** Alternative: vendor them. Why: Espressif's source tarball
  ships `.wrap` files, not the subprojects. The revisions are pinned by commit, so the build
  stays reproducible.
- **The patched QEMU build drops SDL** (Espressif's flags otherwise). Why: the server is
  headless, and this saves image size and build dependencies.
