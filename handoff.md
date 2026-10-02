# Handoff: dryflash ad set (statics + motion)

You are a new session. The job is to make dryflash's ads in the style the owner chose. Read this
file, then load the skills `startup-ad-static` and `startup-ad-motion` (in `~/.claude/skills/`)
and open every image in their `references/` folders before designing anything.

## Product (what is true)

dryflash is an open-source MCP server that lets an AI agent build ESP32 firmware, run it in
Espressif's QEMU, read its serial output, debug it with GDB, decode crashes and inject I2C sensor
data, with no board. Repo: github.com/RomeoCoding/dryflash. Python, runs in Docker.

Allowed claims (use only these):
- "Debug ESP32 firmware without the board."
- Runs your firmware in Espressif's QEMU; build, run, debug, decode crashes.
- Crash → decoded to function, file and line.
- Inject I2C sensor data (ADXL345, ADS1115, any register map), deterministic to the virtual
  nanosecond; replay recorded CSV data.
- Scenario tests in CI with the same result every run.
- 22 MCP tools; works with any MCP client; open source; local (Docker), no account.

Not allowed: anything claiming agents fix bugs better or faster with it (the benchmark has not
shown that), customer logos, user counts, any number not listed above.

## What the owner liked and rejected

Liked (references in the skills): a light Superscale-style product hero; dark case-study posters
(Mira: neon lime light streak, wide display type; Synaptic: purple glass spheres, glass card); a
bold flat logo grid; a 6 s "HUD brand loop" with a glossy 3D logo mark, emissive lime grooves and
glitch transitions.

Rejected (a 54 s film in `demo/film/`, kept for reference only): literal 3D models of the dev
board ("goofy and needless") and screens full of terminal JSON ("blocks of text no one is going to
read"). Do not reuse its look.

## Brand assets

- New logo (made for this brief, v1, open to iteration): `brand/logo/dryflash-mark.svg` (uses
  `currentColor`), `brand/logo/dryflash-tile-ink-lime.svg`, preview `brand/logo/lockup-preview.png`.
  Concept: a geometric "d" split by one diagonal slash, read as the flash, and as "struck through"
  (no board). The lockup and four tile colourways are on the **Logo** page of Figma file
  `XC3xufd2NYRrebhviNPG2w` ("dryflash — film & brand"); the wordmark is Geist SemiBold, −5 %
  tracking.
- Palette proposal: ink `#0B0C0E`, lime `#D4FF3A` (accent), bone `#F4F3EF`, electric blue `#2B2FFF`
  (tile only). The film's solder-amber palette is retired.
- The Figma file's other pages (Brand, Film) belong to the rejected film; leave them, work on new
  pages.

## Deliverables

Static (skill `startup-ad-static`):
1. Light product hero, 2000×1050, plus 1080×1350. Product visual = a clean UI card that shows one
   true feature (e.g. a crash decoded to `main.c:21`, or a sensor waveform card), not a terminal.
2. Dark case-study poster, 1504×1128, plus 1080×1350: wide display wordmark, lime mark, one light
   streak, metadata row `Project: DRYFLASH / Services: ESP32 EMULATION / Field: DEVTOOLS`.
3. Logo tiles 400×400 in the four colourways plus a 1024 app-icon version.

Motion (skill `startup-ad-motion`):
4. HUD brand loop, 6–8 s, 1600×1200 at 60 fps, plus 1080×1080 and 1080×1920: the 3D dryflash mark
   (glossy black, the slash edges glowing lime), material states joined by glitch transitions.
5. Optional, only if the owner wants it after seeing 1–4: a 15–20 s product motion cut.

Put everything under `brand/ads/` (statics) and `brand/motion/` (videos + .blend + scripts).
Large binaries (mp4, .blend) go in `.gitignore`; commit scripts and SVGs.

## Process (the owner wants check-ins)

1. Read the skills and references. Propose the two static directions as **one still each** and
   wait for feedback before making more sizes.
2. For motion, show one still of the hero state, then a 2 s test, before the full render.
3. Keep `.claude/session-summary.md` current (owner's global rule). Local git only: commit with the
   Co-Authored-By trailer, never push.

## Environment notes (learned the hard way)

- Windows 11, Git Bash and PowerShell. Docker Desktop with about 6.6 GB of RAM. The host runs low
  on memory: run heavy work one job at a time; long renders go in the background with
  `blender -b file.blend -a`.
- Blender 5.2 with the MCP add-on (protocol 11, slightly behind; `execute_blender_code` works).
  Eevee on an AMD iGPU: about 4–10 s per 1080p frame at 64 samples. Sketchfab/Poly Haven are
  disabled (not needed: no hardware models).
- Figma: student team, `create_new_file` and `use_figma` work. PNG export has no alpha (use the
  black/white difference matte in the skills). Boolean subtract keeps the bottom-most layer.
- No ffmpeg on PATH: `pip install imageio-ffmpeg` provides one; Blender also encodes.
- Fonts for local rendering: download the OFL files from github.com/google/fonts and make static
  instances with `fontTools.varLib.instancer` (Blender needs one static file per weight).
- Python 3.14 on the host has Pillow and numpy; `pyte` is installed.
