#!/usr/bin/env python3
"""Render the ClearStack logo: a pixel-art flower in a clear glass of water.

Standard library only. Writes assets/logo.png next to this script.
"""
import math
import struct
import zlib
from pathlib import Path

W, H, SCALE = 32, 44, 10

EMPTY = (0, 0, 0, 0)
PETAL = (242, 139, 130, 255)
PETAL_LIGHT = (250, 184, 170, 255)
PETAL_DARK = (201, 84, 92, 255)
CENTER = (246, 201, 69, 255)
CENTER_DARK = (214, 150, 40, 255)
STEM = (95, 165, 90, 255)
STEM_DARK = (61, 122, 58, 255)
OUTLINE = (58, 44, 60, 255)
GLASS_EDGE = (120, 150, 170, 255)
GLASS_RIM = (225, 240, 248, 255)
GLASS_FILL = (200, 225, 240, 60)
WATER = (140, 195, 230, 110)
WATER_TOP = (225, 243, 252, 210)
HIGHLIGHT = (255, 255, 255, 170)
HIGHLIGHT_SOFT = (255, 255, 255, 90)
SHADOW = (0, 0, 0, 45)

GLASS_TOP, WATER_LINE, GLASS_BOTTOM = 22, 28, 41

px = [[EMPTY] * W for _ in range(H)]


def put(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        px[y][x] = c


def glass_span(y):
    """Inner x range of the glass at row y."""
    return 10, 21


def in_glass(x, y):
    lo, hi = glass_span(y)
    return GLASS_TOP <= y <= GLASS_BOTTOM and lo <= x <= hi


def blend(fg, bg):
    """Paint fg under a translucent glass colour bg, keeping the result opaque enough to read."""
    a = bg[3] / 255
    return (*(round(f * (1 - a) + b * a) for f, b in zip(fg[:3], bg[:3])), 255)


# Flower head: five petals around a centre. Each pixel belongs to its nearest
# petal, and a darker line marks where two petals meet, so they read as separate.
cx, cy = 16, 7
petals = [(cx + 3.3 * math.cos(math.radians(-90 + i * 72)), cy + 3.3 * math.sin(math.radians(-90 + i * 72)))
          for i in range(5)]
owner = {}
for y in range(H):
    for x in range(W):
        dists = [math.hypot(x - px_c, y - py_c) for px_c, py_c in petals]
        i = min(range(5), key=dists.__getitem__)
        if dists[i] <= 2.4:
            owner[(x, y)] = i
            dx, dy = x - petals[i][0], y - petals[i][1]
            put(x, y, PETAL_LIGHT if dx + dy < -1.2 else PETAL_DARK if dx + dy > 1.6 else PETAL)
for (x, y), i in owner.items():
    if any(owner.get((x + dx, y + dy), i) != i for dx, dy in ((1, 0), (0, 1))):
        put(x, y, PETAL_DARK)
for y in range(H):
    for x in range(W):
        d = math.hypot(x - cx, y - cy)
        if d <= 1.7:
            put(x, y, CENTER_DARK if x - cx + y - cy > 0.8 else CENTER)

# Stem above the glass, with one leaf.
for y in range(11, GLASS_TOP):
    put(16, y, STEM)
    put(17, y, STEM_DARK)
for x, y in [(13, 15), (14, 15), (12, 16), (13, 16), (14, 16), (15, 16), (13, 17), (14, 17), (15, 17)]:
    put(x, y, STEM if y < 17 else STEM_DARK)

# Outline everything drawn so far (flower, stem, leaf).
solid = {(x, y) for y in range(H) for x in range(W) if px[y][x][3] == 255}
for x, y in solid:
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if (nx, ny) not in solid and 0 <= nx < W and 0 <= ny < H and ny < GLASS_TOP:
            put(nx, ny, OUTLINE)

# Glass body: translucent fill, water below the line.
for y in range(GLASS_TOP, GLASS_BOTTOM + 1):
    lo, hi = glass_span(y)
    for x in range(lo, hi + 1):
        put(x, y, WATER if y > WATER_LINE else GLASS_FILL)

# Stem seen through the glass. Below the waterline refraction shifts it one pixel right.
for y in range(GLASS_TOP, GLASS_BOTTOM - 1):
    shift = 1 if y > WATER_LINE else 0
    tint = WATER if y > WATER_LINE else GLASS_FILL
    put(16 + shift, y, blend(STEM, tint))
    put(17 + shift, y, blend(STEM_DARK, tint))
for x, y in [(18, 32), (19, 32), (19, 33), (18, 33)]:
    put(x + 1, y, blend(STEM, WATER))

# Water surface, rim, walls, base, highlights, shadow.
lo, hi = glass_span(WATER_LINE)
for x in range(lo, hi + 1):
    put(x, WATER_LINE, WATER_TOP)
for y in range(GLASS_TOP, GLASS_BOTTOM + 1):
    lo, hi = glass_span(y)
    put(lo - 1, y, GLASS_EDGE)
    put(hi + 1, y, GLASS_EDGE)
for x in range(9, 23):
    put(x, GLASS_TOP - 1, GLASS_RIM if 10 <= x <= 21 else GLASS_EDGE)
for x in range(10, 22):
    put(x, GLASS_BOTTOM + 1, GLASS_EDGE)
for y in range(GLASS_TOP + 2, GLASS_BOTTOM - 3):
    put(12, y, HIGHLIGHT)
    if y < GLASS_TOP + 8:
        put(13, y, HIGHLIGHT_SOFT)
put(20, GLASS_TOP + 2, HIGHLIGHT_SOFT)
put(20, GLASS_TOP + 3, HIGHLIGHT_SOFT)
for x in range(11, 21):
    put(x, GLASS_BOTTOM + 2, SHADOW)


def write_png(path):
    raw = b""
    for y in range(H * SCALE):
        row = px[y // SCALE]
        raw += b"\x00" + b"".join(bytes(row[x // SCALE]) for x in range(W * SCALE))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr = struct.pack(">IIBBBBB", W * SCALE, H * SCALE, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


write_png(Path(__file__).with_name("logo.png"))
