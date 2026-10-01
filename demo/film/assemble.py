"""Cut the dryflash film in Blender's sequencer and render it to MP4.

  blender -b --factory-startup -P assemble.py -- [--preview N]

Sources (all in this folder): render3d/f_0001..0450.png (Blender 3D shots), term1/ term2/ (real
session, render_term.py), overlays/*.png (Figma exports with recovered alpha), term_timing.json.
"""
import bpy, json, os, sys

FILM = os.path.dirname(os.path.abspath(__file__))
FPS = 30
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PREVIEW = int(argv[argv.index("--preview") + 1]) if "--preview" in argv else 0

sc = bpy.context.scene
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
sc.render.resolution_percentage = 100
sc.render.fps = FPS
try:
    sc.view_settings.view_transform = "Standard"   # sources are already display-referred PNGs
    sc.view_settings.look = "None"
except TypeError as e:
    print("view transform:", e)
sed = sc.sequence_editor_create()
S = sed.strips
INK = (10 / 255, 11 / 255, 13 / 255)

def srgb_to_lin(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)

def seq(name, folder, files, channel, start):
    s = S.new_image(name, os.path.join(FILM, folder, files[0]), channel, start)
    for f in files[1:]:
        s.elements.append(f)
    return s

def still(name, png, channel, start, length):
    s = S.new_image(name, os.path.join(FILM, "overlays", png), channel, start)
    s.frame_final_duration = length
    s.blend_type = "ALPHA_OVER"
    return s

def color(name, channel, start, length, rgb=INK):
    s = S.new_effect(name, "COLOR", channel, start, length=length)
    s.color = rgb
    return s

def fade(s, fin=0, fout=0, rise=0):
    a, b = s.frame_final_start, s.frame_final_end
    if fin:
        s.blend_alpha = 0.0; s.keyframe_insert("blend_alpha", frame=a)
        s.blend_alpha = 1.0; s.keyframe_insert("blend_alpha", frame=a + fin)
        if rise:
            base = s.transform.offset_y
            s.transform.offset_y = base - rise; s.transform.keyframe_insert("offset_y", frame=a)
            s.transform.offset_y = base; s.transform.keyframe_insert("offset_y", frame=a + fin + 4)
    if fout:
        s.blend_alpha = 1.0; s.keyframe_insert("blend_alpha", frame=b - fout)
        s.blend_alpha = 0.0; s.keyframe_insert("blend_alpha", frame=b)

def push(s, z=1.015):
    a, b = s.frame_final_start, s.frame_final_end
    s.transform.scale_x = s.transform.scale_y = 1.0
    s.transform.keyframe_insert("scale_x", frame=a); s.transform.keyframe_insert("scale_y", frame=a)
    s.transform.scale_x = s.transform.scale_y = z
    s.transform.keyframe_insert("scale_x", frame=b); s.transform.keyframe_insert("scale_y", frame=b)

def frames3d(a, b):
    return [f"f_{i:04d}.png" for i in range(a, b + 1)]

timing = json.load(open(os.path.join(FILM, "term_timing.json")))
n1, n2 = timing["term1"]["frames"], timing["term2"]["frames"]
m1, m2 = timing["term1"]["marks"], timing["term2"]["marks"]

cur = 1
# ---- cold open: three 3D shots with quiet title lines
A = seq("A macro", "render3d", frames3d(1, 120), 2, cur)
t = still("T1", "tl1.png", 5, cur + 30, 90); t.transform.offset_y = 730; fade(t, 8, 6, rise=10)  # top: the macro is bright below
B = seq("B wide", "render3d", frames3d(121, 210), 2, cur + 120)
t = still("T2", "tl2.png", 5, cur + 127, 83); fade(t, 8, 6, rise=10)
C = seq("C scan", "render3d", frames3d(211, 300), 2, cur + 210)
t = still("T3", "tl3.png", 5, cur + 262, 38); fade(t, 6, 0, rise=8)
cur += 300
# ---- wordmark on ink, cursor blinking at 1 Hz
color("WM bg", 2, cur, 75)
wm = still("WM", "wm_nocursor.png", 5, cur, 75); fade(wm, 10, 0)
for k in range(3):
    still(f"WM cursor {k}", "wm.png", 6, cur + k * 30, 15)
cur += 75
# ---- the real session, with callouts cut to the moment each step appears
T1 = seq("Term crash", "term1", [f"{i:04d}.png" for i in range(1, n1 + 1)], 2, cur); push(T1)
cuts1 = [("ov01.png", 5), ("ov02.png", m1["start"]), ("ov03.png", m1["type"]),
         ("ov04.png", m1["decode"]), ("ov05.png", m1["fix"]), (None, n1 + 1)]
for (png, f0), (_, f1) in zip(cuts1, cuts1[1:]):
    s = still(png, png, 5, cur + max(f0 - 4, 0), f1 - max(f0 - 4, 0)); fade(s, 6, 4, rise=14)
cur += n1
T2 = seq("Term sensor", "term2", [f"{i:04d}.png" for i in range(1, n2 + 1)], 2, cur); push(T2)
cuts2 = [("ov06.png", 1), ("ov07.png", m2["fail"]), ("ov08.png", m2["pass"]), (None, n2 + 1)]
for (png, f0), (_, f1) in zip(cuts2, cuts2[1:]):
    s = still(png, png, 5, cur + max(f0 - 4, 0), f1 - max(f0 - 4, 0)); fade(s, 6, 4, rise=14)
cur += n2
# ---- kinetic words: hard cuts, 16 frames each
color("KW bg", 2, cur, 6 * 16)
for k, w in enumerate(("build", "boot", "break", "decode", "inject", "verify")):
    still(f"KW {w}", f"kw_{w}.png", 5, cur + k * 16, 16)
cur += 6 * 16
color("T4 bg", 2, cur, 84)
t = still("T4", "tl4.png", 5, cur, 84); fade(t, 8, 8, rise=10)
cur += 84
# ---- end: the solid board, end card
D = seq("D end", "render3d", frames3d(301, 450), 2, cur)
e = still("END", "end.png", 5, cur + 18, 150 - 18); fade(e, 14, 0, rise=12)
cur += 150
end = cur - 1
# ---- fade in from ink, fade out to ink
fi = color("fade in", 9, 1, 14); fi.blend_type = "ALPHA_OVER"; fade(fi, 0, 14)
fo = color("fade out", 9, end - 17, 18); fo.blend_type = "ALPHA_OVER"; fade(fo, 18, 0)

score = os.path.join(FILM, "score.wav")
if os.path.exists(score):
    S.new_sound("score", score, 12, 1)
sc.frame_start, sc.frame_end = 1, end
r = sc.render
if PREVIEW:
    r.image_settings.file_format = "PNG"
    r.filepath = os.path.join(FILM, "preview", "p_")
    sc.frame_start = sc.frame_end = PREVIEW
else:
    if hasattr(r.image_settings, "media_type"):
        r.image_settings.media_type = "VIDEO"   # Blender 5: video output is a media type
    r.image_settings.file_format = "FFMPEG"
    r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
    r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.ffmpeg_preset = "GOOD"
    r.ffmpeg.gopsize = 15
    r.ffmpeg.audio_codec = "AAC"; r.ffmpeg.audio_bitrate = 256; r.ffmpeg.audio_channels = "STEREO"
    r.ffmpeg.audio_mixrate = 48000
    r.filepath = os.path.join(FILM, "dryflash_film.mp4")
print("timeline frames:", end, "seconds:", end / FPS)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(FILM, "dryflash_edit.blend"))
bpy.ops.render.render(animation=True)
