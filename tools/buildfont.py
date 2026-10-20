"""Build a subset web font that looks like the in-game font.

Latin comes from the game's ascii.png bitmap; everything else from GNU Unifont, which is
what Minecraft itself uses for CJK. Glyphs are drawn as pixel squares, so the font stays
crisp at 16px and 32px.

Units: one Unifont pixel = P font units; one ascii.png pixel = 2P (the game draws Unifont at
half scale next to ascii.png).
"""
import io

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from PIL import Image

P = 64
UPM = 16 * P          # em = 8 ascii pixels = 16 Unifont pixels
ASC, DESC = 14 * P, 2 * P
ALWAYS = " 0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.,:;!?%/()[]-+×·★✓—–'\"<>_#…"


def _runs(row):
    """Yield (start, length) for each run of lit pixels in a row of booleans."""
    x = 0
    while x < len(row):
        if row[x]:
            s = x
            while x < len(row) and row[x]:
                x += 1
            yield s, x - s
        else:
            x += 1


def _ascii_glyphs(ascii_png):
    img = Image.open(io.BytesIO(ascii_png)).convert("RGBA")
    out = {}
    for code in range(33, 127):
        cx, cy = (code % 16) * 8, (code // 16) * 8
        on = [[img.getpixel((cx + x, cy + y))[3] > 0 for x in range(8)] for y in range(8)]
        cols = [x for x in range(8) if any(on[y][x] for y in range(8))]
        width = (max(cols) + 1) if cols else 3
        rects = []
        for y in range(8):  # row 6 sits on the baseline, row 7 is the descender
            for s, n in _runs(on[y]):
                rects.append((s * 2 * P, (6 - y) * 2 * P, n * 2 * P, 2 * P))
        out[chr(code)] = ((width + 1) * 2 * P, rects)
    out[" "] = (4 * 2 * P, [])
    return out


def _unifont_glyphs(unifont_hex, need):
    out = {}
    for line in unifont_hex.splitlines():
        if ":" not in line:
            continue
        cp, hx = line.strip().split(":")
        ch = chr(int(cp, 16))
        if ch not in need:
            continue
        w = 8 if len(hx) == 32 else 16
        rows = [int(hx[i * w // 4:(i + 1) * w // 4], 16) for i in range(16)]
        on = [[bool((rows[y] >> (w - 1 - x)) & 1) for x in range(w)] for y in range(16)]
        cols = [x for x in range(w) if any(on[y][x] for y in range(16))]
        if not cols:
            out[ch] = (w // 2 * P, [])
            continue
        left, right = min(cols), max(cols)
        rects = [((s - left) * P, (13 - y) * P, n * P, P) for y in range(16) for s, n in _runs(on[y])]
        out[ch] = ((right - left + 1) * P + 2 * P, rects)
    return out


def build_font(out_path, text, ascii_png, unifont_hex):
    """Write a WOFF2 font covering every character in `text` (plus basic ASCII)."""
    chars = {c for c in set(text) | set(ALWAYS) if ord(c) >= 32}
    glyphs = _ascii_glyphs(ascii_png)
    glyphs = {c: g for c, g in glyphs.items() if c in chars}
    glyphs.update(_unifont_glyphs(unifont_hex, {c for c in chars if c not in glyphs}))

    name = lambda c: "u%04X" % ord(c)
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder([".notdef"] + [name(c) for c in sorted(glyphs)])
    fb.setupCharacterMap({ord(c): name(c) for c in glyphs})
    outlines, metrics = {".notdef": TTGlyphPen(None).glyph()}, {".notdef": (8 * P, 0)}
    for c, (adv, rects) in glyphs.items():
        pen = TTGlyphPen(None)
        for x, y, w, h in rects:
            pen.moveTo((x, y)); pen.lineTo((x, y + h)); pen.lineTo((x + w, y + h)); pen.lineTo((x + w, y)); pen.closePath()
        outlines[name(c)] = pen.glyph()
        metrics[name(c)] = (adv, min([r[0] for r in rects], default=0))
    fb.setupGlyf(outlines)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASC + 2 * P, descent=-(DESC + 2 * P))
    fb.setupNameTable({"familyName": "MCPixel", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ASC + 2 * P, sTypoDescender=-(DESC + 2 * P),
                usWinAscent=ASC + 2 * P, usWinDescent=DESC + 2 * P)
    fb.setupPost()
    buf = io.BytesIO()
    fb.save(buf)
    font = TTFont(io.BytesIO(buf.getvalue()))
    font.flavor = "woff2"
    font.save(out_path)
    return len(glyphs)
