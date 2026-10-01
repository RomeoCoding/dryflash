"""Synthesised sound design for the dryflash film, locked to the edit's frame map (assemble.py).

No samples and no music library: every sound is generated here, so the track has no licensing
strings attached. Writes score.wav (48 kHz stereo, 16-bit).
"""
import json, os, wave
import numpy as np

FILM = os.path.dirname(os.path.abspath(__file__))
SR, FPS = 48000, 30
rng = np.random.default_rng(11)
timing = json.load(open(os.path.join(FILM, "term_timing.json")))
n1, n2 = timing["term1"]["frames"], timing["term2"]["frames"]
# frame map, identical to assemble.py
T_A, T_C, T_WM = 1, 211, 301
T_TERM1 = 376
T_TERM2 = T_TERM1 + n1
T_KW = T_TERM2 + n2
T_T4 = T_KW + 96
T_D = T_T4 + 84
END = T_D + 150 - 1
N = int(END / FPS * SR) + SR // 2
L = np.zeros(N); R = np.zeros(N)

def at(frame): return int((frame - 1) / FPS * SR)
def env_exp(n, tau): return np.exp(-np.arange(n) / (tau * SR))
def add(sig, start, gain=1.0, pan=0.0):
    s = max(start, 0); e = min(start + len(sig), N); sig = sig[: e - s] * gain
    L[s:e] += sig * np.sqrt(0.5 * (1 - pan)); R[s:e] += sig * np.sqrt(0.5 * (1 + pan))
def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR); y = np.empty_like(x); acc = 0.0
    for i in range(len(x)):  # one-pole; only used on short signals
        acc = (1 - a) * x[i] + a * acc; y[i] = acc
    return y
def lp_fft(x, cutoff):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR); X *= 1 / np.sqrt(1 + (f / cutoff) ** 4); return np.fft.irfft(X, len(x))
def hp_fft(x, cutoff):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR); X *= 1 / np.sqrt(1 + (cutoff / np.maximum(f, 1)) ** 4); return np.fft.irfft(X, len(x))

# --- drone bed: low fifths, slow breathing, under everything except the kinetic hits
t = np.arange(N) / SR
drone = sum(a * np.sin(2 * np.pi * f * t + p) for f, a, p in ((55, 1.0, 0), (82.41, 0.55, 1.1), (110, 0.35, 2.3), (164.8, 0.12, 0.4)))
drone *= 0.75 + 0.25 * np.sin(2 * np.pi * 0.11 * t)
air = lp_fft(rng.standard_normal(N), 900) * 0.25
bed = drone * 0.095 + air * 0.08
lvl = np.interp(t, [0, 3, (T_TERM1 - 1) / FPS, T_TERM1 / FPS, T_KW / FPS - 0.2, T_KW / FPS, T_T4 / FPS, END / FPS - 0.6, END / FPS],
                [0, 1, 1, 0.55, 0.55, 0.0, 0.9, 1.0, 0])
L += bed * lvl; R += np.roll(bed, 240) * lvl

# --- light sweep over the macro shot: filtered noise that moves left to right
n = at(110) - at(T_A)
sw = lp_fft(rng.standard_normal(n), 2500) * np.sin(np.linspace(0, np.pi, n)) ** 2
for i, pan in enumerate(np.linspace(-0.8, 0.8, 8)):
    seg = slice(i * n // 8, (i + 1) * n // 8)
    part = np.zeros(n); part[seg] = sw[seg]; add(part, at(T_A), 0.05, pan)

# --- riser under the scan line (C shot, 3D frames 222..288), cut dead at the wordmark
a, b = at(T_C + 11), at(T_WM)
n = b - a; tt = np.arange(n) / SR
f = 180 * (1800 / 180) ** (tt / tt[-1])
riser = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35 + hp_fft(rng.standard_normal(n), 1500) * 0.5
riser *= (tt / tt[-1]) ** 2.2
add(riser, a, 0.10, -0.3); add(riser, a + 300, 0.10, 0.3)

def impact(frame, size=1.0):
    n = int(1.6 * SR); tt = np.arange(n) / SR
    f = 34 + 46 * np.exp(-tt / 0.07)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(n, 0.45)
    click = np.zeros(n); k = int(0.004 * SR); click[:k] = rng.standard_normal(k) * np.linspace(1, 0, k)
    tail = lp_fft(rng.standard_normal(n), 400) * env_exp(n, 0.6) * 0.4
    sig = (sub * 0.9 + hp_fft(click, 2000) * 0.5 + tail) * size
    add(sig, at(frame), 0.55)

def tock(frame, freq=880, gain=0.05, pan=0.0):
    n = int(0.25 * SR); tt = np.arange(n) / SR
    sig = (np.sin(2 * np.pi * freq * tt) + 0.35 * np.sin(2 * np.pi * freq * 1.5 * tt)) * env_exp(n, 0.06)
    add(sig, at(frame), gain, pan)

def two_note(frame, f1, f2, gain):
    tock(frame, f1, gain); tock(frame + 4, f2, gain)

impact(T_WM, 1.0)
# --- the session: soft key ticks for typed characters, a tock per callout, tones on results
for base, data in ((T_TERM1, timing["term1"]), (T_TERM2, timing["term2"])):
    for i, s in enumerate(data["keys"]):
        if i % 2: continue
        n = int(0.012 * SR)
        tick = hp_fft(rng.standard_normal(n), 3500) * env_exp(n, 0.0025)
        add(tick, at(base) + int(s * SR), 0.05 * (0.7 + 0.6 * rng.random()), rng.uniform(-0.3, 0.3))
m1, m2 = timing["term1"]["marks"], timing["term2"]["marks"]
for k in ("build", "start", "type", "decode", "fix"):
    tock(T_TERM1 + m1[k] - 4, 660, 0.04)
tock(T_TERM2, 660, 0.04)
two_note(T_TERM1 + m1["pass"] - 1, 659.3, 987.8, 0.05)
two_note(T_TERM2 + m2["fail"] - 1, 220.0, 174.6, 0.07)
tock(T_TERM2 + m2["fix"] - 4, 660, 0.04)
two_note(T_TERM2 + m2["pass"] - 1, 659.3, 987.8, 0.05)

# --- kinetic words: one hit per cut, the last one bigger
for k in range(6):
    n = int(0.5 * SR); tt = np.arange(n) / SR
    f = 48 + 80 * np.exp(-tt / 0.03)
    kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(n, 0.16)
    snap = hp_fft(rng.standard_normal(n), 2500) * env_exp(n, 0.025)
    add(kick * 0.9 + snap * 0.35, at(T_KW + k * 16), 0.42 if k < 5 else 0.6)

# --- end: swell into the end card, final low hit, long tail
a = at(T_D); n = at(T_D + 18) - a
sw = lp_fft(rng.standard_normal(n), 1200) * np.linspace(0, 1, n) ** 3
add(sw, a, 0.12, -0.2); add(sw[::-1][::-1], a, 0.12, 0.2)
impact(T_D + 18, 0.8)

# --- room: short convolution reverb, then master
ir_n = int(0.9 * SR)
ir = rng.standard_normal(ir_n) * env_exp(ir_n, 0.22); ir = lp_fft(ir, 5000); ir /= np.abs(ir).sum() / 6
def conv(x):
    m = 1 << int(np.ceil(np.log2(len(x) + ir_n)))
    return np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(ir, m), m)[: len(x)]
L = L + 0.18 * conv(L); R = R + 0.18 * conv(R)
mix = np.stack([L, R], axis=1)
mix = np.tanh(mix * 1.4) / np.tanh(1.4)
mix *= 0.89 / np.max(np.abs(mix))
fade = int(0.4 * SR); mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
with wave.open(os.path.join(FILM, "score.wav"), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
print("score.wav", round(len(mix) / SR, 2), "s; timeline end frame", END)
