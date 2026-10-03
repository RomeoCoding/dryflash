"""SSD1306 display capture: decode the I2C write stream into a framebuffer, render it, read text off it.

Behaviour follows the Solomon Systech SSD1306 datasheet, Rev 1.1 (Apr 2008); section numbers in the
comments refer to it. The decoder sees exactly the bytes the firmware wrote (i2c-sim-sensor in
stream mode reports each write transfer whole), so nothing is inferred from timing.
"""

from __future__ import annotations

import struct
import zlib

from .font5x7 import FONT5X7

WIDTH = 128
PAGES = 8

# Command bytes that take arguments, and how many (section 9, command table; 8Dh from the charge
# pump appendix). Every other byte value is a one-byte command.
_ARGS = {0x81: 1, 0x8D: 1, 0x20: 1, 0x21: 2, 0x22: 2, 0xA8: 1, 0xD3: 1, 0xD5: 1, 0xD9: 1, 0xDA: 1,
         0xDB: 1, 0x26: 6, 0x27: 6, 0x29: 5, 0x2A: 5, 0xA3: 2}


class Ssd1306State:
    def __init__(self):
        self.ram = bytearray(WIDTH * PAGES)  # GDDRAM: page-major, bit 0 = top row of the page (8.7)
        self.on = False                      # AEh at reset (9)
        self.inverted = False
        self.entire_on = False
        self.contrast = 0x7F
        self.mode = 2                        # page addressing at reset (10.1.3)
        self.col_start, self.col_end = 0, WIDTH - 1
        self.page_start, self.page_end = 0, PAGES - 1
        self.col, self.page = 0, 0
        self.start_line = 0
        self.offset = 0
        self.mux = 64
        self.seg_remap = False
        self.com_remap = False
        self.charge_pump = False
        self.data_bytes = 0
        self.commands = 0
        self._cmd: list[int] = []            # command byte plus the arguments received so far

    # ----- write stream ----------------------------------------------------------------------------
    def feed_transfer(self, data: bytes) -> None:
        """One I2C write transfer: control byte(s) then command or data bytes (8.1.5.2)."""
        i = 0
        while i < len(data):
            ctrl = data[i]
            i += 1
            is_data = bool(ctrl & 0x40)       # D/C#
            if ctrl & 0x80:                   # Co = 1: one byte, then another control byte
                if i < len(data):
                    self._byte(data[i], is_data)
                    i += 1
                continue
            for b in data[i:]:                # Co = 0: the rest of the transfer
                self._byte(b, is_data)
            return

    def _byte(self, b: int, is_data: bool) -> None:
        if is_data:
            self._data(b)
        else:
            self._command_byte(b)

    def _data(self, b: int) -> None:
        self.ram[self.page * WIDTH + self.col] = b
        self.data_bytes += 1
        if self.mode == 0:      # horizontal (10.1.3)
            self.col += 1
            if self.col > self.col_end:
                self.col = self.col_start
                self.page = self.page + 1 if self.page < self.page_end else self.page_start
        elif self.mode == 1:    # vertical
            self.page += 1
            if self.page > self.page_end:
                self.page = self.page_start
                self.col = self.col + 1 if self.col < self.col_end else self.col_start
        else:                   # page: the column wraps, the page stays
            self.col = self.col + 1 if self.col < WIDTH - 1 else self.col_start

    def _command_byte(self, b: int) -> None:
        self._cmd.append(b)
        if len(self._cmd) - 1 < _ARGS.get(self._cmd[0], 0):
            return
        cmd, args = self._cmd[0], self._cmd[1:]
        self._cmd = []
        self.commands += 1
        if cmd in (0xAE, 0xAF):
            self.on = cmd == 0xAF
        elif cmd in (0xA6, 0xA7):
            self.inverted = cmd == 0xA7
        elif cmd in (0xA4, 0xA5):
            self.entire_on = cmd == 0xA5
        elif cmd == 0x81:
            self.contrast = args[0]
        elif cmd == 0x20:
            self.mode = args[0] & 3 if args[0] & 3 != 3 else self.mode  # 11b is invalid
        elif cmd == 0x21:       # also resets the column pointer (10.1.4)
            self.col_start, self.col_end = args[0] & 0x7F, args[1] & 0x7F
            self.col = self.col_start
        elif cmd == 0x22:
            self.page_start, self.page_end = args[0] & 7, args[1] & 7
            self.page = self.page_start
        elif 0xB0 <= cmd <= 0xB7:
            self.page = cmd & 7
        elif cmd <= 0x0F:       # lower column nibble, page mode
            self.col_start = (self.col_start & 0xF0) | cmd
            self.col = self.col_start
        elif 0x10 <= cmd <= 0x1F:
            self.col_start = (self.col_start & 0x0F) | ((cmd & 0x07) << 4)
            self.col = self.col_start
        elif 0x40 <= cmd <= 0x7F:
            self.start_line = cmd & 0x3F
        elif cmd in (0xA0, 0xA1):
            self.seg_remap = cmd == 0xA1
        elif cmd in (0xC0, 0xC8):
            self.com_remap = cmd == 0xC8
        elif cmd == 0xA8:
            self.mux = (args[0] & 0x3F) + 1 if (args[0] & 0x3F) >= 15 else self.mux  # 16-64 MUX
        elif cmd == 0xD3:
            self.offset = args[0] & 0x3F
        elif cmd == 0x8D:
            self.charge_pump = bool(args[0] & 0x04)

    # ----- what the panel shows --------------------------------------------------------------------
    def ram_pixel(self, col: int, row: int) -> int:
        return (self.ram[(row // 8) * WIDTH + col] >> (row % 8)) & 1

    def image(self) -> list[list[int]]:
        """Pixels as seen on the panel, rows top to bottom.

        Oriented for the common 0.96"/0.91" modules, whose drivers (Adafruit, U8g2, esp-idf
        examples) send A1h and C8h so that GDDRAM column 0 / row 0 appears top left. A0h or C0h
        mirror the image accordingly. COM pin configuration (DAh) is assumed to match the module.
        """
        h = self.mux
        img = []
        for y in range(h):
            r = y if self.com_remap else h - 1 - y
            row_in_ram = (r + self.start_line + self.offset) % 64
            line = []
            for x in range(WIDTH):
                col = x if self.seg_remap else WIDTH - 1 - x
                p = 1 if self.entire_on else self.ram_pixel(col, row_in_ram)
                line.append(p ^ 1 if self.inverted else p)
            img.append(line)
        return img

    def describe(self) -> dict:
        return {"on": self.on, "inverted": self.inverted, "entire_display_on": self.entire_on,
                "contrast": self.contrast, "width": WIDTH, "height": self.mux,
                "addressing_mode": ("horizontal", "vertical", "page")[self.mode],
                "charge_pump": self.charge_pump, "data_bytes": self.data_bytes, "commands": self.commands}


def text_art(img: list[list[int]]) -> dict:
    """Half-block rendering cropped to the lit area (two pixel rows per text line)."""
    lit = [(x, y) for y, row in enumerate(img) for x, p in enumerate(row) if p]
    if not lit:
        return {"art": "", "box": None}
    x0, x1 = min(p[0] for p in lit), max(p[0] for p in lit)
    y0, y1 = min(p[1] for p in lit), max(p[1] for p in lit)
    y0 -= y0 % 2
    lines = []
    for y in range(y0, y1 + 1, 2):
        top, bot = img[y], img[y + 1] if y + 1 < len(img) else [0] * len(img[0])
        lines.append("".join(" ▀▄█"[top[x] | bot[x] << 1] for x in range(x0, x1 + 1)).rstrip())
    return {"art": "\n".join(lines), "box": {"x": x0, "y": y0, "width": x1 - x0 + 1, "height": y1 - y0 + 1}}


_GLYPH_BY_COLUMNS = {cols: ch for ch, cols in FONT5X7.items() if any(cols)}


def read_text(img: list[list[int]], scales=(1, 2, 3, 4)) -> list[str]:
    """Text drawn with the Adafruit-GFX classic 5x7 font at integer sizes, one string per text line.

    A glyph is accepted only if all its s x s blocks are uniform and the 6s x 8s cell around it is
    otherwise blank, which rejects partial matches inside larger shapes. Other fonts are not read.
    """
    h, w = len(img), len(img[0]) if img else 0
    found: list[tuple[int, int, int, str]] = []  # (y, x, scale, char)

    def blank(x: int, y: int) -> bool:
        return not (0 <= x < w and 0 <= y < h) or not img[y][x]

    for s in scales:
        for y0 in range(0, h - 7 * s + 1):
            codes = [sum(img[y0 + k * s][x] << k for k in range(8) if y0 + k * s < h) for x in range(w)]
            for x0 in range(0, w - 5 * s + 1):
                ch = _GLYPH_BY_COLUMNS.get(tuple(codes[x0 + j * s] for j in range(5)))
                if ch is None or not _glyph_exact(img, x0, y0, s, FONT5X7[ch]):
                    continue
                cell_ok = all(blank(x0 + 5 * s + dx, y0 + dy) for dx in range(s) for dy in range(8 * s)) and \
                    all(blank(x0 - 1 - dx, y0 + dy) for dx in range(s) for dy in range(8 * s))
                if cell_ok:
                    found.append((y0, x0, s, ch))
    # A larger glyph wins over smaller matches inside its box
    found.sort(key=lambda f: -f[2])
    kept: list[tuple[int, int, int, str]] = []
    for y, x, s, ch in found:
        if not any(ky <= y < ky + 8 * ks and kx <= x < kx + 6 * ks for ky, kx, ks, _ in kept if ks > s):
            kept.append((y, x, s, ch))
    lines: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for y, x, s, ch in kept:
        lines.setdefault((y, s), []).append((x, ch))
    out = []
    for (y, s) in sorted(lines):
        chars = sorted(lines[(y, s)])
        text, prev = "", None
        for x, ch in chars:
            if prev is not None and x - prev > 6 * s + s // 2:
                text += " " * max(1, round((x - prev) / (6 * s)) - 1)
            text += ch
            prev = x
        out.append(text)
    return out


def _glyph_exact(img, x0: int, y0: int, s: int, cols: tuple[int, ...]) -> bool:
    h = len(img)
    for j, col in enumerate(cols):
        for k in range(8):
            bit = (col >> k) & 1
            for dy in range(s):
                y = y0 + k * s + dy
                if y >= h:
                    if bit:
                        return False
                    continue
                row = img[y]
                for dx in range(s):
                    if row[x0 + j * s + dx] != bit:
                        return False
    return True


def write_png(img: list[list[int]], path, scale: int = 4) -> None:
    """Grayscale PNG of the panel (lit pixels white), each pixel scale x scale."""
    h, w = len(img), len(img[0])
    raw = bytearray()
    for row in img:
        line = bytes(255 if p else 0 for p in row for _ in range(scale))
        for _ in range(scale):
            raw += b"\x00" + line

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w * scale, h * scale, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
