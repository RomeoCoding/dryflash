"""Render the recorded dryflash session (asciicast) into 1920x1080 PNG frames for the film.

Real output only: the bytes come from demo.cast, replayed through a terminal emulator (pyte).
Long waits (spinner-only spans) are time-lapsed to WAIT_S, and the window shows a TIME-LAPSE tag
while that happens; the spinner itself keeps printing the real elapsed seconds.
"""
import json, os, re, sys
import pyte
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FPS, COLS, ROWS = 30, 100, 32
WAIT_S = 0.9
W, H = 1920, 1080
FONT = ImageFont.truetype(os.path.join(HERE, "fonts", "JetBrainsMono-Regular.ttf"), 18)
FONTB = ImageFont.truetype(os.path.join(HERE, "fonts", "JetBrainsMono-Bold.ttf"), 18)
FONT_UI = ImageFont.truetype(os.path.join(HERE, "fonts", "JetBrainsMono-Medium.ttf"), 15)
CW = FONT.getlength("M")
LH = 26
PAD_X, PAD_Y, BAR = 30, 22, 46
PW = int(COLS * CW + 2 * PAD_X)
PH = int(ROWS * LH + 2 * PAD_Y + BAR)
PX, PY = W - 64 - PW, (H - PH) // 2

def rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
INK, GRAPHITE, LINE, BONE, MUTE, SOLDER, FAULT, PASS = map(rgb, ("#0A0B0D", "#121418", "#2A2D33", "#EDE9E2", "#8A8F98", "#F2A33A", "#E5534B", "#8FD19E"))
TEXT, DIM = rgb("#C9C6C0"), rgb("#5C6168")
PALETTE = {"default": TEXT, "cyan": MUTE, "yellow": SOLDER, "green": PASS, "red": FAULT, "magenta": MUTE,
           "white": BONE, "brightcyan": MUTE}
SPIN = re.compile("[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]")
ESC = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")][1:]

def segment(ev, t0, t1):
    """Events in [t0, t1) with times remapped: spinner-only runs longer than WAIT_S are squeezed."""
    sel = [(t, d) for t, _, d in ev if t0 <= t < t1]
    out, lapses, shift = [], [], 0.0
    i = 0
    while i < len(sel):
        t, d = sel[i]
        if SPIN.search(d):
            j = i
            while j + 1 < len(sel) and SPIN.search(sel[j + 1][1]) and not ESC.sub("", sel[j + 1][1]).strip("\r ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏0123456789s…_abcdefghijklmnopqrstuvwxyz").strip():
                j += 1
            span = sel[j][0] - t
            if span > WAIT_S * 1.5:
                k = WAIT_S / span
                a = t - t0 - shift
                for tt, dd in sel[i:j + 1]:
                    out.append((a + (tt - t) * k, dd))
                lapses.append((a, a + WAIT_S, span))
                shift += span - WAIT_S
                i = j + 1
                continue
        out.append((t - t0 - shift, d))
        i += 1
    return out, lapses

HILITE = [(re.compile(r"apply_setting \(main/main\.c:21\)|NULL pointer dereference"), SOLDER),
          (re.compile(r'"passed": false|outside \[1\.229'), FAULT),
          (re.compile(r'"passed": true'), PASS)]

def draw_frame(screen, t, lapses, typing_recent, title):
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    # panel with a soft drop (no glow): one darker offset rectangle
    d.rounded_rectangle((PX, PY + 10, PX + PW, PY + PH + 10), 16, fill=(6, 7, 8))
    d.rounded_rectangle((PX, PY, PX + PW, PY + PH), 16, fill=GRAPHITE, outline=LINE, width=1)
    d.line((PX + 1, PY + BAR, PX + PW - 1, PY + BAR), fill=LINE, width=1)
    for k, c in enumerate((LINE, LINE, LINE)):
        cx = PX + 26 + k * 20; d.ellipse((cx - 5, PY + BAR // 2 - 5, cx + 5, PY + BAR // 2 + 5), fill=c)
    d.text((PX + 96, PY + BAR // 2), title, font=FONT_UI, fill=MUTE, anchor="lm")
    lapse = next((x for x in lapses if x[0] <= t < x[1]), None)
    if lapse:
        tag = f"TIME-LAPSE  {lapse[2]:.0f} s → {WAIT_S:.1f} s"
        tw = FONT_UI.getlength(tag)
        d.rounded_rectangle((PX + PW - 28 - tw - 16, PY + 12, PX + PW - 28, PY + BAR - 12), 4, outline=SOLDER, width=1)
        d.text((PX + PW - 28 - tw - 8, PY + BAR // 2), tag, font=FONT_UI, fill=SOLDER, anchor="lm")
    x0, y0 = PX + PAD_X, PY + BAR + PAD_Y
    for r in range(ROWS):
        line = screen.buffer[r]
        rowtext = "".join(line[c].data for c in range(COLS))
        y = y0 + r * LH
        for rx, col in HILITE:
            m = rx.search(rowtext)
            if m:
                a = x0 + m.start() * CW - 4; b = x0 + m.end() * CW + 4
                d.rectangle((a, y + 1, b, y + LH - 3), fill=tuple(int(c * 0.16 + g * 0.84) for c, g in zip(col, GRAPHITE)))
                d.rectangle((a, y + LH - 4, b, y + LH - 3), fill=col)
                break
        c = 0
        while c < COLS:
            ch = line[c]
            style = (ch.fg, ch.bold)
            run = ch.data; c2 = c + 1
            while c2 < COLS and (line[c2].fg, line[c2].bold) == style:
                run += line[c2].data; c2 += 1
            if run.strip():
                fg = PALETTE.get(ch.fg, TEXT)
                if ch.bold and ch.fg == "default": fg = BONE
                d.text((x0 + c * CW, y + LH // 2), run, font=FONTB if ch.bold else FONT, fill=fg, anchor="lm")
            c = c2
    if typing_recent:
        cx = x0 + screen.cursor.x * CW; cy = y0 + screen.cursor.y * LH
        d.rectangle((cx, cy + 3, cx + CW - 1, cy + LH - 3), fill=SOLDER)
    return im

def render(events, lapses, outdir, title, markers, tail_s=0.8):
    """Writes the frames; returns (frame count, {marker: first 1-based frame whose screen shows it})."""
    os.makedirs(outdir, exist_ok=True)
    screen = pyte.Screen(COLS, ROWS); stream = pyte.Stream(screen)
    end = (events[-1][0] if events else 0) + tail_s
    n = int(end * FPS) + 1
    i, last_type, seen, keys = 0, -9, {}, []
    for f in range(n):
        t = f / FPS
        while i < len(events) and events[i][0] <= t:
            data = events[i][1]
            stream.feed(data.replace("\n", "\r\n") if "\r\n" not in data else data)
            if len(ESC.sub("", data)) <= 2 and not SPIN.search(data) and ESC.sub("", data).strip():
                last_type = events[i][0]; keys.append(round(events[i][0], 4))
            i += 1
        shown = "\n".join(screen.display)
        for k, s in markers.items():
            if k not in seen and s in shown: seen[k] = f + 1
        draw_frame(screen, t, lapses, t - last_type < 0.35, title).save(os.path.join(outdir, f"{f + 1:04d}.png"))
    return n, seen, keys

if __name__ == "__main__":
    ev = load(os.path.join(HERE, "demo.cast"))
    marks = {}
    for t, _, d in ev:
        p = ESC.sub("", d)
        if "1. A crash" in p and "s1" not in marks: marks["s1"] = t
        if "2. A sensor" in p and "s2" not in marks: marks["s2"] = t
        if "Both bugs" in p and "end" not in marks: marks["end"] = t
    # each segment starts just before its section banner (the screen clear) and ends before the next
    s1, l1 = segment(ev, marks["s1"] - 0.05, marks["s2"] - 0.05)
    s2, l2 = segment(ev, marks["s2"] - 0.05, marks["end"] - 0.02)
    title = "agent  ⟷  dryflash   ·   MCP over stdio"
    m1 = {"build": "project_build {", "start": "emu_start {", "type": '"text": "set name"', "decode": "decode_panic {",
          "fix": "agent edits the source", "test": "test_run {", "pass": '"passed": true'}
    m2 = {"fail": '"passed": false', "fix": "agent edits the source", "pass": '"passed": true'}
    n1, k1, keys1 = render(s1, l1, os.path.join(HERE, "term1"), title, m1)
    n2, k2, keys2 = render(s2, l2, os.path.join(HERE, "term2"), title, m2)
    json.dump({"term1": {"frames": n1, "lapses": l1, "marks": k1, "keys": keys1}, "term2": {"frames": n2, "lapses": l2, "marks": k2, "keys": keys2}},
              open(os.path.join(HERE, "term_timing.json"), "w"), indent=1)
    print("term1", n1, "frames", k1, "; term2", n2, "frames", k2)
