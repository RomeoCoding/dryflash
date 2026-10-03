"""The 'classic' 5x7 font of the Adafruit GFX library (glcdfont.c, release 1.12.6), ASCII 0x20-0x7E.

Each glyph is 5 column bytes, bit 0 at the top. Used to read text off emulated displays.

Copyright (c) 2012 Adafruit Industries. All rights reserved. BSD License: redistribution and use
in source and binary forms, with or without modification, are permitted provided that the
copyright notice, this list of conditions and the following disclaimer are retained (see the
Adafruit-GFX-Library license.txt for the full text, which applies to this table).
"""

GLYPHS_HEX = """
    00 00 00 00 00 00 00 5f 00 00 00 07 00 07 00 14 7f 14 7f 14
    24 2a 7f 2a 12 23 13 08 64 62 36 49 56 20 50 00 08 07 03 00
    00 1c 22 41 00 00 41 22 1c 00 2a 1c 7f 1c 2a 08 08 3e 08 08
    00 80 70 30 00 08 08 08 08 08 00 00 60 60 00 20 10 08 04 02
    3e 51 49 45 3e 00 42 7f 40 00 72 49 49 49 46 21 41 49 4d 33
    18 14 12 7f 10 27 45 45 45 39 3c 4a 49 49 31 41 21 11 09 07
    36 49 49 49 36 46 49 49 29 1e 00 00 14 00 00 00 40 34 00 00
    00 08 14 22 41 14 14 14 14 14 00 41 22 14 08 02 01 59 09 06
    3e 41 5d 59 4e 7c 12 11 12 7c 7f 49 49 49 36 3e 41 41 41 22
    7f 41 41 41 3e 7f 49 49 49 41 7f 09 09 09 01 3e 41 41 51 73
    7f 08 08 08 7f 00 41 7f 41 00 20 40 41 3f 01 7f 08 14 22 41
    7f 40 40 40 40 7f 02 1c 02 7f 7f 04 08 10 7f 3e 41 41 41 3e
    7f 09 09 09 06 3e 41 51 21 5e 7f 09 19 29 46 26 49 49 49 32
    03 01 7f 01 03 3f 40 40 40 3f 1f 20 40 20 1f 3f 40 38 40 3f
    63 14 08 14 63 03 04 78 04 03 61 59 49 4d 43 00 7f 41 41 41
    02 04 08 10 20 00 41 41 41 7f 04 02 01 02 04 40 40 40 40 40
    00 03 07 08 00 20 54 54 78 40 7f 28 44 44 38 38 44 44 44 28
    38 44 44 28 7f 38 54 54 54 18 00 08 7e 09 02 18 a4 a4 9c 78
    7f 08 04 04 78 00 44 7d 40 00 20 40 40 3d 00 7f 10 28 44 00
    00 41 7f 40 00 7c 04 78 04 78 7c 08 04 04 78 38 44 44 44 38
    fc 18 24 24 18 18 24 24 18 fc 7c 08 04 04 08 48 54 54 54 24
    04 04 3f 44 24 3c 40 40 20 7c 1c 20 40 20 1c 3c 40 30 40 3c
    44 28 10 28 44 4c 90 90 90 7c 44 64 54 4c 44 00 08 36 41 00
    00 00 77 00 00 00 41 36 08 00 02 01 02 04 02
"""

FONT5X7: dict[str, tuple[int, ...]] = {}
_b = bytes.fromhex("".join(GLYPHS_HEX.split()))
for _i in range(len(_b) // 5):
    FONT5X7[chr(0x20 + _i)] = tuple(_b[5 * _i:5 * _i + 5])
