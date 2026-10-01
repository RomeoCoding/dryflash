# Film: how it was made

`dryflash_film.mp4` (54 s, 1920×1080, 30 fps, H.264 + AAC; not committed, see .gitignore) is cut
from four kinds of source. None of it is stock footage or a mock-up:

| source | tool | what |
|---|---|---|
| 3D board shots | Blender 5.2 (`dryflash_board.blend`, Eevee) | an ESP32-DevKitC modelled to real proportions; macro, wide, the scan-line "ghost" shot and the end hero |
| type and end card | Figma, file "dryflash — film & brand" (Brand and Film pages) | brand board, callouts, kinetic words, title lines, end card; exported twice (on black and on white) so the alpha can be recovered exactly |
| terminal footage | `record_cast.py` + `render_term.py` | a real run of `demo/run_demo.py` recorded as an asciicast and replayed through a terminal emulator (pyte) into frames. Waits longer than 1.35 s are time-lapsed to 0.9 s and labelled TIME-LAPSE on screen; the spinner keeps printing the real seconds |
| sound | `sound.py` | synthesised with numpy (drone, riser, impacts, key ticks from the recorded keystrokes, result tones); no samples, no music library |

`assemble.py` cuts it all together in Blender's sequencer and renders the MP4:

```sh
python record_cast.py demo.cast "warm-up done: both apps are built" docker run --rm -t -v <repo>:/opt/dryflash \
    dryflash-sensors /opt/venv/bin/python /opt/dryflash/demo/run_demo.py --warm-up --clear --pace 0.6 --typing 90
python render_term.py          # term1/, term2/, term_timing.json
python sound.py                # score.wav
blender -b --factory-startup -P assemble.py
```

The scripts expect their inputs next to them (`fonts/` with Archivo and JetBrains Mono static
instances, `overlays/` with the Figma exports, `render3d/` with the 450 rendered 3D frames).
Copy says only what the run shows; it makes no claim about agents doing better with the tool.
