# food-picture-01 entry: a juicy cheeseburger, drawn 100% in code.
#
# Python 3.13, standard library only (zlib + struct for the PNG encoder).
# No network, no randomness at run time: every pixel is a deterministic
# function of its coordinates, so two runs write byte-identical files.
#
# The picture: a big cheeseburger, hero-centred, on a dark walnut table
# under warm light from above. Golden glossy top bun with sesame seeds,
# ruffled green lettuce, a red tomato slice, melted cheddar dripping over
# a thick charred patty. No hands, no text.
#
#   mkdir -p out && MAKEFUN_OUTPUT_DIR=out python3 main.py
import math
import os
import struct
import zlib

W = 1024
H = 1024
buf = bytearray(W * H * 3)


def clamp(v, lo=0, hi=255):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return (int(lerp(c1[0], c2[0], t)), int(lerp(c1[1], c2[1], t)),
            int(lerp(c1[2], c2[2], t)))


def idx(x, y):
    return (y * W + x) * 3


def put(x, y, r, g, b):
    if 0 <= x < W and 0 <= y < H:
        i = idx(x, y)
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b


def blend_px(x, y, r, g, b, a):
    """Blend colour (r,g,b) over pixel (x,y) with alpha a in [0,1]."""
    if a <= 0 or not (0 <= x < W and 0 <= y < H):
        return
    i = idx(x, y)
    if a >= 1:
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b
        return
    buf[i] = int(buf[i] + (r - buf[i]) * a)
    buf[i + 1] = int(buf[i + 1] + (g - buf[i + 1]) * a)
    buf[i + 2] = int(buf[i + 2] + (b - buf[i + 2]) * a)


def span(y, x0, x1, col):
    """Solid horizontal run on row y (x0, x1 are floats, 1px feather)."""
    if y < 0 or y >= H:
        return
    lo = int(math.ceil(x0))
    hi = int(math.floor(x1))
    r, g, b = col
    if hi > lo:
        i0 = (y * W + max(lo, 0)) * 3
        i1 = (y * W + min(hi, W)) * 3
        if i1 > i0:
            buf[i0:i1] = bytes((r, g, b)) * ((i1 - i0) // 3)
    # feather the two edge pixels
    if 0 <= lo - 1 < W and lo > x0:
        blend_px(lo - 1, y, r, g, b, lo - x0)
    if 0 <= hi < W and hi < x1:
        blend_px(hi, y, r, g, b, x1 - hi)


def blend_span(y, x0, x1, col, a):
    """Translucent horizontal run."""
    if y < 0 or y >= H or a <= 0:
        return
    lo = max(int(math.ceil(x0)), 0)
    hi = min(int(math.floor(x1)), W)
    r, g, b = col
    for x in range(lo, hi):
        blend_px(x, y, r, g, b, a)


def ellipse_rows(cx, cy, rx, ry, top, bot, squash=1.0):
    """Yield (y, x0, x1, colour) row spans of a filled ellipse with a
    vertical gradient from top colour to bottom colour."""
    y0 = max(0, int(math.ceil(cy - ry)))
    y1 = min(H - 1, int(math.floor(cy + ry)))
    for y in range(y0, y1 + 1):
        dy = (y - cy) / ry
        if abs(dy) >= 1:
            continue
        dx = rx * math.sqrt(1 - dy * dy) * squash
        t = (y - (cy - ry)) / (2 * ry)
        yield y, cx - dx, cx + dx, mix(top, bot, t)


def draw_ellipse(cx, cy, rx, ry, top, bot):
    for y, x0, x1, col in ellipse_rows(cx, cy, rx, ry, top, bot):
        span(y, x0, x1, col)


def soft_ellipse(cx, cy, rx, ry, col, alpha, feather=0.22):
    """Elliptical blob with a soft (feathered) edge, alpha at centre.
    Keep bboxes small: this is a per-pixel loop, only for highlights
    and shadows, never for full-frame effects."""
    y0 = max(0, int(cy - ry))
    y1 = min(H - 1, int(cy + ry))
    r0, g0, b0 = col
    buf_local = buf
    for y in range(y0, y1 + 1):
        dy = (y - cy) / ry
        if abs(dy) >= 1:
            continue
        dx = rx * math.sqrt(1 - dy * dy)
        x0 = max(0, int(cx - dx))
        x1 = min(W - 1, int(cx + dx))
        for x in range(x0, x1 + 1):
            ddx = (x - cx) / rx
            d = math.sqrt(ddx * ddx + dy * dy)
            if d >= 1:
                continue
            a = alpha * (1 - max(0.0, (d - (1 - feather)) / feather))
            if a <= 0:
                continue
            i = (y * W + x) * 3
            buf_local[i] = int(buf_local[i] + (r0 - buf_local[i]) * a)
            buf_local[i + 1] = int(buf_local[i + 1] + (g0 - buf_local[i + 1]) * a)
            buf_local[i + 2] = int(buf_local[i + 2] + (b0 - buf_local[i + 2]) * a)


# ---------------------------------------------------------------- deterministic
def hash2(x, y, seed=0):
    """Deterministic pseudo-random in [0,1) from integer coords."""
    h = (x * 374761393 + y * 668265263 + seed * 974634211) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    h = (h ^ (h >> 16)) & 0xFFFFFFFF
    return h / 4294967296.0


def rng(seed):
    """Tiny deterministic LCG generator."""
    s = seed & 0xFFFFFFFF
    while True:
        s = (1664525 * s + 1013904223) & 0xFFFFFFFF
        yield s / 4294967296.0


# ================================================================ background
def draw_background():
    # One banded pass (64 vertical bands x 1024 rows, slice assignment
    # only -- no per-pixel loops): vertical walnut gradient, a warm radial
    # glow from above centre, and darkened corners, all in one formula.
    BAND = 16
    NB = W // BAND
    for y in range(H):
        t = y / (H - 1)
        base = mix((96, 58, 32), (38, 20, 10), t * t * 0.85 + t * 0.15)
        dy = (y - 300) / 560.0
        for b in range(NB):
            xc = b * BAND + BAND / 2
            dx = (xc - 512) / 700.0
            d = math.sqrt(dx * dx + dy * dy)
            col = base
            if d < 1.15:  # warm glow
                ga = (1 - d / 1.15) ** 2 * 0.38
                col = mix(col, (255, 176, 92), ga)
            # corner darkening (vignette baked into the table)
            r2 = ((xc - 512) / 512.0) ** 2 + ((y - 512) / 512.0) ** 2
            if r2 > 0.55:
                va = min(0.30, (r2 - 0.55) / 0.6 * 0.30)
                col = mix(col, (10, 5, 2), va)
            i0 = (y * W + b * BAND) * 3
            buf[i0:i0 + BAND * 3] = bytes(col) * BAND
    # Wood planks: vertical seams.
    for sx in (256, 512, 768):
        for dx in range(-2, 3):
            blend_span(0, sx + dx, sx + dx + 1, (20, 10, 5), 0.35)
    # Grain: long thin darker streaks, wavy, deterministic.
    r = rng(20261114)
    for _ in range(90):
        gx = int(next(r) * W)
        gy = int(next(r) * H)
        glen = int(120 + next(r) * 420)
        gcol = (26, 14, 7) if next(r) < 0.6 else (122, 76, 42)
        ga = 0.05 + next(r) * 0.10
        amp = 2 + next(r) * 5
        ph = next(r) * 6.28
        for s in range(glen):
            x = gx + s
            if x >= W:
                break
            y = gy + int(amp * math.sin(s * 0.02 + ph))
            blend_px(x, y, gcol[0], gcol[1], gcol[2], ga)
            blend_px(x, y + 1, gcol[0], gcol[1], gcol[2], ga * 0.5)
    # Soft shadow where the burger will sit.
    soft_ellipse(512, 868, 400, 58, (12, 6, 3), 0.55, feather=0.35)


# ================================================================ fries
def draw_fry(cx, cy, length, width, angle_deg, seed):
    """One golden fry: a rounded stick rotated by angle_deg."""
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    hw, hl = width / 2.0, length / 2.0
    # bounding box of the rotated rect
    ex = abs(ca) * hl + abs(sa) * hw
    ey = abs(sa) * hl + abs(ca) * hw
    x0, x1 = int(cx - ex - 2), int(cx + ex + 2)
    y0, y1 = int(cy - ey - 2), int(cy + ey + 2)
    for y in range(max(0, y0), min(H, y1 + 1)):
        for x in range(max(0, x0), min(W, x1 + 1)):
            # to stick-local coords (u along length, v across)
            dx, dy = x - cx, y - cy
            u = dx * ca + dy * sa
            v = -dx * sa + dy * ca
            if abs(u) > hl or abs(v) > hw:
                continue
            # rounded ends
            du = max(0.0, abs(u) - (hl - hw))
            dv = max(0.0, abs(v) - (hw - 1))
            d = math.sqrt(du * du + dv * dv)
            if d > hw:
                continue
            t = (u + hl) / (2 * hl)
            col = mix((244, 196, 82), (214, 148, 38), t)
            # crisp darker edge
            edge = max(0.0, (d - (hw - 2.5)) / 2.5)
            if edge > 0:
                col = mix(col, (168, 104, 22), min(1.0, edge))
            # toasted tip
            if u > hl - 26:
                col = mix(col, (186, 116, 30), (u - (hl - 26)) / 26 * 0.6)
            blend_px(x, y, col[0], col[1], col[2], 1.0)
    # salt specks
    r = rng(seed)
    for _ in range(14):
        sx = cx + int((next(r) - 0.5) * length * 0.8)
        sy = cy + int((next(r) - 0.5) * width * 0.7)
        put(sx, sy, 255, 250, 235)
        put(sx + 1, sy, 250, 244, 228)


def draw_fries():
    # Short sticks, mostly hidden behind the bun: only their golden tips
    # peek out on the right, so they read as fries, not straws.
    draw_fry(660, 430, 210, 34, -18, 11)
    draw_fry(720, 400, 230, 34, -10, 22)
    draw_fry(772, 432, 200, 32, -26, 33)
    draw_fry(640, 472, 190, 32, -30, 44)


# ================================================================ burger
def draw_bottom_bun():
    # Golden heel, tucked under the patty so the stack has no air gaps.
    for y, x0, x1, col in ellipse_rows(512, 762, 302, 82, (222, 158, 62),
                                      (150, 92, 26)):
        span(y, x0, x1, col)
    # toasted bottom rim
    for y in range(800, 846):
        dy = (y - 762) / 82
        if abs(dy) >= 1:
            continue
        dx = 302 * math.sqrt(1 - dy * dy)
        span(y, 512 - dx, 512 + dx, mix((150, 92, 26), (110, 60, 16),
                                        (y - 800) / 46))
    # soft sheen across the front of the heel
    soft_ellipse(470, 760, 220, 26, (255, 214, 130), 0.20)


def draw_patty():
    # Thick charred patty, wider than the heel, its top tucked under the
    # cheese and its bottom resting on the heel: no gap anywhere.
    for y in range(630, 748):
        dy = (y - 688) / 58
        if abs(dy) >= 1:
            continue
        dx = 322 * math.sqrt(1 - dy * dy)
        wob = 7 * math.sin(y * 0.35) + 5 * math.sin(y * 0.11 + 2.0)
        t = (y - 630) / 118
        col = mix((152, 90, 44), (66, 36, 18), t)
        span(y, 512 - dx + wob * 0.4, 512 + dx + wob * 0.4, col)
    # char speckles
    r = rng(777)
    for _ in range(320):
        x = int(512 + (next(r) - 0.5) * 580)
        y = int(642 + next(r) * 92)
        dx = (x - 512) / 322
        dy = (y - 688) / 58
        if dx * dx + dy * dy > 0.92:
            continue
        c = (38, 18, 8) if next(r) < 0.55 else (156, 92, 42)
        a = 0.35 + next(r) * 0.4
        blend_px(x, y, c[0], c[1], c[2], a)
        if next(r) < 0.4:
            blend_px(x + 1, y, c[0], c[1], c[2], a * 0.6)
    # juicy gloss line along the patty's front
    for x in range(260, 765):
        dx = (x - 512) / 322
        if dx * dx > 0.9:
            continue
        y = 730 - int(14 * (1 - dx * dx))
        blend_px(x, y, 190, 116, 52, 0.35)
        blend_px(x, y + 1, 190, 116, 52, 0.2)
    # warm rim where the cheese melts onto the patty
    for x in range(280, 745):
        dx = (x - 512) / 322
        if dx * dx > 0.92:
            continue
        y = 652 + int(8 * dx * dx)
        blend_px(x, y, 214, 130, 58, 0.5)


def draw_cheese():
    # Molten cheddar band, overlapping the tomato above and the patty
    # below, with short irregular drips melting onto the patty.
    for y in range(598, 656):
        dy = (y - 627) / 29
        if abs(dy) >= 1:
            continue
        dx = 320 * math.sqrt(1 - dy * dy)
        t = (y - 598) / 58
        col = mix((255, 196, 44), (240, 138, 12), t)
        span(y, 512 - dx, 512 + dx, col)
    # drips: short rounded tongues melting onto the patty.
    for (dx0, dl, dw) in ((-210, 34, 38), (-58, 48, 46), (96, 38, 36),
                          (218, 30, 32)):
        cx = 512 + dx0
        for y in range(642, 642 + dl):
            t = (y - 642) / dl
            w = dw * 0.5 * math.sqrt(max(0.0, 1 - (t / 0.92) ** 2))
            col = mix((250, 176, 30), (232, 122, 10), t)
            span(y, cx - w, cx + w, col)
    # gloss streaks on the cheese
    for x in range(300, 420):
        blend_px(x, 614 + int(4 * math.sin(x * 0.05)), 255, 226, 120, 0.5)
    for x in range(600, 720):
        blend_px(x, 618 + int(4 * math.sin(x * 0.045 + 1)), 255, 226, 120, 0.45)


def draw_tomato():
    # Red tomato slice, thick and juicy, tucked under the lettuce.
    for y, x0, x1, col in ellipse_rows(512, 585, 325, 32, (226, 62, 38),
                                      (178, 32, 22)):
        span(y, x0, x1, col)
    # paler flesh inside
    for y, x0, x1, col in ellipse_rows(512, 585, 298, 22, (240, 104, 74),
                                      (222, 76, 52)):
        span(y, x0, x1, col)
    # juicy highlight
    for x in range(330, 700):
        dx = (x - 512) / 325
        if dx * dx > 0.85:
            continue
        y = 570 + int(6 * (1 - dx * dx))
        blend_px(x, y, 255, 150, 110, 0.5)


def draw_lettuce():
    # Thick ruffled lettuce, two overlapping frill bands so it reads as
    # leafy volume, not a flat stripe; it overlaps the bun above and the
    # tomato below.
    for y in range(500, 588):
        t = (y - 500) / 88
        base = 340 - 28 * t
        wob = 15 * math.sin(y * 0.12) + 8 * math.sin(y * 0.05 + 1.5)
        hw = base + wob
        col = mix((146, 198, 86), (72, 136, 42), t)
        span(y, 512 - hw, 512 + hw, col)
    # second frill band, offset, for depth
    for y in range(540, 592):
        t = (y - 540) / 52
        wob = 14 * math.sin(y * 0.11 + 2.2) + 7 * math.sin(y * 0.06)
        hw = 344 - 18 * t + wob
        col = mix((120, 178, 70), (62, 122, 38), t)
        span(y, 512 - hw, 512 + hw, col)
    # darker veins
    r = rng(4242)
    for _ in range(60):
        x = int(512 + (next(r) - 0.5) * 660)
        y = int(508 + next(r) * 74)
        blend_px(x, y, 58, 112, 34, 0.5)
        blend_px(x, y + 1, 58, 112, 34, 0.35)
    # light frill tips on both edges
    for y in range(500, 592, 2):
        wob = 15 * math.sin(y * 0.12) + 8 * math.sin(y * 0.05 + 1.5)
        hw = 340 - 28 * ((y - 500) / 88) + wob
        blend_px(int(512 - hw), y, 178, 220, 108, 0.8)
        blend_px(int(512 + hw), y, 178, 220, 108, 0.8)


def draw_top_bun():
    # Golden dome, wider than tall so it reads as a bun, not a helmet.
    for y in range(310, 550):
        dy = (y - 548) / 238
        if abs(dy) > 1:
            continue
        # dome: half-ellipse, widest at the bottom
        dx = 345 * math.sqrt(max(0.0, 1 - dy * dy))
        t = (y - 310) / 238
        col = mix((246, 190, 96), (196, 128, 44), t)
        span(y, 512 - dx, 512 + dx, col)
    # warm side shading on the right
    soft_ellipse(780, 450, 120, 170, (120, 62, 18), 0.18, feather=0.4)
    # glossy highlight, upper left
    soft_ellipse(400, 370, 190, 90, (255, 224, 150), 0.42, feather=0.45)
    soft_ellipse(370, 350, 90, 44, (255, 240, 190), 0.5, feather=0.5)
    # toasted bottom edge of the dome
    for y in range(522, 550):
        dy = (y - 548) / 238
        dx = 345 * math.sqrt(max(0.0, 1 - dy * dy))
        span(y, 512 - dx, 512 + dx,
             mix((196, 128, 44), (158, 96, 28), (y - 522) / 28))


def draw_seed(cx, cy, angle_deg, s=1.0):
    """One sesame seed: pale ellipse, shaded rim, bright top."""
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    rx, ry = 11 * s, 5.5 * s
    for y in range(int(cy - 9), int(cy + 10)):
        for x in range(int(cx - 14), int(cx + 15)):
            dx, dy = x - cx, y - cy
            u = dx * ca + dy * sa
            v = -dx * sa + dy * ca
            d = (u / rx) ** 2 + (v / ry) ** 2
            if d > 1:
                continue
            if d > 0.72:
                col = (196, 158, 88)  # rim
            elif v < -1:
                col = (252, 236, 196)  # lit top
            else:
                col = (240, 214, 158)
            blend_px(x, y, col[0], col[1], col[2], 1.0)


def draw_seeds():
    # Fewer, bigger, warmer seeds, all on the upper dome.
    seeds = [
        (410, 360, -18), (480, 338, 12), (552, 352, -8), (616, 382, 24),
        (362, 420, 30), (448, 408, -24), (528, 420, 8), (606, 436, -14),
        (668, 420, 18), (404, 478, 6), (492, 480, -20), (582, 486, 14),
    ]
    for cx, cy, ang in seeds:
        draw_seed(cx, cy, ang, s=1.25)


# ================================================================ garnish
def draw_garnish():
    # Scattered sesame seeds and herb leaves on the table.
    for (x, y, a) in [(212, 880, 20), (252, 902, -14), (812, 884, 8),
                      (842, 908, -22), (300, 924, 12)]:
        draw_seed(x, y, a, s=0.8)
    # a few green herb leaves
    for (lx, ly, ang) in [(196, 830, -30), (836, 836, 24), (872, 872, -12)]:
        a = math.radians(ang)
        ca, sa = math.cos(a), math.sin(a)
        for yy in range(ly - 12, ly + 13):
            for xx in range(lx - 18, lx + 19):
                dx, dy = xx - lx, yy - ly
                u = dx * ca + dy * sa
                v = -dx * sa + dy * ca
                if (u / 16) ** 2 + (v / 7) ** 2 <= 1:
                    blend_px(xx, yy, 74, 138, 52, 0.9)


# ================================================================ vignette
def draw_vignette():
    # Corner darkening is baked into the background pass already (the
    # burger fills the centre, so nothing more is needed here).
    return


# ================================================================ PNG
def write_png(path):
    raw = bytearray()
    for y in range(H):
        raw.append(0)  # filter: None
        raw += buf[y * W * 3:(y + 1) * W * 3]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main():
    draw_background()
    # Fries were tried and removed: the sticks poking out of the bun read
    # as straws and hurt the picture more than they helped.
    draw_bottom_bun()
    draw_patty()
    draw_cheese()
    draw_tomato()
    draw_lettuce()
    draw_top_bun()
    draw_seeds()
    draw_garnish()
    draw_vignette()
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    size = write_png(os.path.join(out_dir, "entry.png"))
    print(f"wrote {size} bytes")


if __name__ == "__main__":
    main()
