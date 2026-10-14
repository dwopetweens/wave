"""Builds the Signal trace Lottie files from the approved BearStack SVG geometry.

Mirrors the CSS timeline in signal-trace.html (5 s loop, 60 fps).
Writes, per colour: the 5 s loop and a play-once intro (ends on the full lockup),
each as Lottie JSON and as dotLottie.
Usage: python3 make_lottie.py <export_dir>
"""
import json
import re
import sys
import zipfile

FPS, LOOP = 60, 5.0
OP = int(FPS * LOOP)
INTRO_OP = int(FPS * 3.4)  # build-in lands at ~2.9 s; hold on the full lockup until 3.4 s
PAD = 16  # logo clear space at master size
W, H = 408.08 + 2 * PAD, 80 + 2 * PAD

E_OUT = (0.22, 1, 0.36, 1)
E_IN = (0.64, 0, 0.78, 0)
E_SHIFT = (0.65, 0, 0.35, 1)
E_ORBIT = (0.45, 0, 0.2, 1)
LIN = (0, 0, 1, 1)

BONE, ESPRESSO, ORANGE = "#F4F1E8", "#17130A", "#FF6B00"

# Signal B symbol, 100 x 100 box (bearstack-symbol-*.svg)
RECTS = {
    "anchor-top": (17, 14, 18, 32, 4),
    "anchor-bottom": (17, 54, 18, 32, 4),
    "terminal-top": (43, 14, 33, 14, 7),
    "signal-pill": (43, 38, 25, 24, 12),
    "terminal-bottom": (43, 72, 33, 14, 7),
}
DOT = (79, 50, 7)

# Wordmark outlines from bearstack-logo-primary.svg, one path per letter
WORDMARK = """M21.184 62.0H6.464V19.12H21.504Q29.44 19.12 33.92 22.128Q38.4 25.136 38.4 30.512Q38.4 38.256 31.04 40.56Q39.04 42.416 39.04 50.16Q39.04 62.0 21.184 62.0ZM12.992 24.56V37.936H21.696Q27.072 37.936 29.472 36.272Q31.872 34.608 31.872 30.96Q31.872 27.824 29.248 26.192Q26.624 24.56 21.824 24.56ZM12.992 43.376V56.56H21.504Q26.624 56.56 29.568 55.088Q32.512 53.616 32.512 49.712Q32.512 46.256 29.92 44.816Q27.328 43.376 21.696 43.376Z M61.568 62.704Q54.4 62.704 49.664 58.032Q44.928 53.36 44.928 46.128Q44.928 39.216 49.408 34.48Q53.888 29.744 60.8 29.744Q67.776 29.744 71.968 34.192Q76.16 38.64 76.16 45.36V47.92H51.072Q51.584 52.016 54.464 54.544Q57.344 57.072 61.504 57.072Q67.904 57.072 70.656 51.952L75.52 54.448Q73.472 58.48 69.856 60.592Q66.24 62.704 61.568 62.704ZM51.328 43.824H69.824Q69.632 40.048 67.136 37.744Q64.64 35.44 60.736 35.44Q56.896 35.44 54.368 37.808Q51.84 40.176 51.328 43.824Z M97.152 62.768Q90.432 62.768 85.92 57.968Q81.408 53.168 81.408 46.256Q81.408 39.472 86.208 34.672Q91.008 29.872 98.112 29.872Q105.216 29.872 110.016 34.576Q114.816 39.28 114.816 46.256V62.0H108.8V56.496Q107.008 59.44 103.968 61.104Q100.928 62.768 97.152 62.768ZM108.48 46.32Q108.48 41.968 105.472 38.896Q102.464 35.824 98.112 35.824Q93.76 35.824 90.752 38.896Q87.744 41.968 87.744 46.32Q87.744 50.608 90.752 53.68Q93.76 56.752 98.112 56.752Q102.464 56.752 105.472 53.68Q108.48 50.608 108.48 46.32Z M129.92 62.0H123.584V43.312Q123.584 37.424 126.88 33.712Q130.176 30.0 136.128 30.0Q139.392 30.0 141.76 31.152V37.424Q139.456 36.08 136.704 36.08Q133.568 36.08 131.744 38.096Q129.92 40.112 129.92 43.568Z M159.872 62.704Q154.368 62.704 150.144 60.304Q145.92 57.904 144.0 53.552L149.504 50.864Q152.064 56.56 159.872 56.56Q163.712 56.56 166.208 54.8Q168.704 53.04 168.704 49.968Q168.704 48.624 168.16 47.568Q167.616 46.512 166.912 45.904Q166.208 45.296 164.736 44.784Q163.264 44.272 162.272 44.048Q161.28 43.824 159.296 43.44Q156.928 42.992 155.264 42.544Q153.6 42.096 151.456 41.136Q149.312 40.176 148.0 38.928Q146.688 37.68 145.76 35.632Q144.832 33.584 144.832 30.96Q144.832 25.648 149.056 22.064Q153.28 18.48 159.424 18.48Q164.48 18.48 168.48 20.816Q172.48 23.152 174.336 27.44L168.896 30.256Q166.08 24.56 159.168 24.56Q155.84 24.56 153.568 26.32Q151.296 28.08 151.296 30.768Q151.296 32.112 151.872 33.136Q152.448 34.16 153.184 34.8Q153.92 35.44 155.392 35.984Q156.864 36.528 157.984 36.784Q159.104 37.04 161.024 37.424Q163.392 37.872 165.024 38.32Q166.656 38.768 168.736 39.728Q170.816 40.688 172.096 41.936Q173.376 43.184 174.304 45.232Q175.232 47.28 175.232 49.904Q175.232 55.536 170.816 59.12Q166.4 62.704 159.872 62.704Z M197.184 62.832Q191.424 62.832 188.32 59.536Q185.216 56.24 185.216 50.736V36.144H179.008V30.64H185.216V22.512H191.552V30.64H203.584V36.144H191.552V50.544Q191.552 53.616 193.216 55.344Q194.88 57.072 197.76 57.072Q200.96 57.072 203.584 55.216V61.04Q200.96 62.832 197.184 62.832Z M225.152 62.768Q218.432 62.768 213.92 57.968Q209.408 53.168 209.408 46.256Q209.408 39.472 214.208 34.672Q219.008 29.872 226.112 29.872Q233.216 29.872 238.016 34.576Q242.816 39.28 242.816 46.256V62.0H236.8V56.496Q235.008 59.44 231.968 61.104Q228.928 62.768 225.152 62.768ZM236.48 46.32Q236.48 41.968 233.472 38.896Q230.464 35.824 226.112 35.824Q221.76 35.824 218.752 38.896Q215.744 41.968 215.744 46.32Q215.744 50.608 218.752 53.68Q221.76 56.752 226.112 56.752Q230.464 56.752 233.472 53.68Q236.48 50.608 236.48 46.32Z M265.984 62.704Q259.264 62.768 254.432 57.936Q249.6 53.104 249.6 46.256Q249.6 39.472 254.4 34.64Q259.2 29.808 265.984 29.872Q270.464 29.872 274.144 31.952Q277.824 34.032 279.936 38.128L274.688 41.072Q271.872 35.888 265.984 35.888Q261.824 35.888 258.88 38.928Q255.936 41.968 255.936 46.256Q255.936 50.544 258.88 53.648Q261.824 56.752 265.984 56.752Q271.872 56.752 274.688 51.568L279.936 54.448Q277.824 58.544 274.144 60.624Q270.464 62.704 265.984 62.704Z M293.696 62.0H287.36V16.176H293.696V43.696H297.536Q297.984 42.608 299.008 41.584L309.056 30.64H316.8L303.296 45.36Q302.72 45.872 302.72 46.256Q302.72 46.64 303.296 47.152L316.736 62.0H308.928L298.944 51.056Q297.92 49.776 297.472 48.688H293.696Z"""
LETTERS = WORDMARK.split(" M")
LETTERS = [LETTERS[0]] + ["M" + s for s in LETTERS[1:]]


def rgba(hex_):
    return [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1]


def frame(pct):
    return round(pct / 100 * OP, 3)


def anim(keys):
    """keys: [(percent, value_list, easing_to_next or None)] -> Lottie animated property."""
    out = []
    for pct, val, ease in keys:
        k = {"t": frame(pct), "s": list(val)}
        if ease is not None:
            n = len(val)
            k["o"] = {"x": [ease[0]] * n, "y": [ease[1]] * n}
            k["i"] = {"x": [ease[2]] * n, "y": [ease[3]] * n}
        out.append(k)
    return {"a": 1, "k": out}


def static(val):
    return {"a": 0, "k": val}


def transform(p=(0, 0), a=(0, 0), s=(100, 100), r=0, o=100):
    wrap = lambda v: v if isinstance(v, dict) else static(list(v) if isinstance(v, tuple) else v)
    return {"p": wrap(p), "a": wrap(a), "s": wrap(s), "r": wrap(r), "o": wrap(o)}


def layer(ind, name, ks, shapes=None, parent=None):
    lyr = {"ddd": 0, "ind": ind, "ty": 4 if shapes is not None else 3, "nm": name, "sr": 1,
           "ks": ks, "ao": 0, "ip": 0, "op": OP, "st": 0, "bm": 0}
    if shapes is not None:
        lyr["shapes"] = shapes
    if parent is not None:
        lyr["parent"] = parent
    return lyr


def group(name, items, color):
    tr = {"ty": "tr", "p": static([0, 0]), "a": static([0, 0]), "s": static([100, 100]),
          "r": static(0), "o": static(100), "sk": static(0), "sa": static(0)}
    fill = {"ty": "fl", "c": static(rgba(color)), "o": static(100), "r": 1, "nm": "Fill"}
    return [{"ty": "gr", "nm": name, "it": items + [fill, tr]}]


def parse_path(d):
    """Absolute M/L/H/V/Q/Z SVG path -> list of Lottie bezier shapes."""
    toks = re.findall(r"[MLHVQZ]|-?\d*\.?\d+", d)
    shapes, cur, start, verts = [], (0.0, 0.0), None, []
    i = 0

    def close():
        if not verts:
            return
        if len(verts) > 1 and abs(verts[-1]["v"][0] - verts[0]["v"][0]) < 1e-6 and abs(verts[-1]["v"][1] - verts[0]["v"][1]) < 1e-6:
            verts[0]["i"] = verts[-1]["i"]
            verts.pop()
        shapes.append({"c": True, "v": [v["v"] for v in verts], "i": [v["i"] for v in verts], "o": [v["o"] for v in verts]})

    def line_to(p):
        verts.append({"v": list(p), "i": [0, 0], "o": [0, 0]})

    while i < len(toks):
        cmd = toks[i]; i += 1
        if cmd == "M":
            close(); verts = []
            cur = (float(toks[i]), float(toks[i + 1])); i += 2
            start = cur
            verts.append({"v": list(cur), "i": [0, 0], "o": [0, 0]})
        elif cmd == "L":
            cur = (float(toks[i]), float(toks[i + 1])); i += 2; line_to(cur)
        elif cmd == "H":
            cur = (float(toks[i]), cur[1]); i += 1; line_to(cur)
        elif cmd == "V":
            cur = (cur[0], float(toks[i])); i += 1; line_to(cur)
        elif cmd == "Q":
            q = (float(toks[i]), float(toks[i + 1])); p = (float(toks[i + 2]), float(toks[i + 3])); i += 4
            c1 = (cur[0] + 2 / 3 * (q[0] - cur[0]), cur[1] + 2 / 3 * (q[1] - cur[1]))
            c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
            verts[-1]["o"] = [c1[0] - cur[0], c1[1] - cur[1]]
            verts.append({"v": list(p), "i": [c2[0] - p[0], c2[1] - p[1]], "o": [0, 0]})
            cur = p
        elif cmd == "Z":
            close(); verts = []; cur = start
    close()
    return shapes


def cubic(ease, x):
    """Evaluate a CSS cubic-bezier easing at progress x."""
    x1, y1, x2, y2 = ease
    bez = lambda t, a, b: 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if bez(mid, x1, x2) < x:
            lo = mid
        else:
            hi = mid
    return bez((lo + hi) / 2, y1, y2)


def build(sym, wm):
    layers, ind = [], 0

    def add(lyr):
        layers.append(lyr)
        return lyr["ind"]

    ind += 1
    shift = add(layer(ind, "Shift", transform(p=anim([
        (0, [PAD + 171, PAD], LIN), (28, [PAD + 171, PAD], E_SHIFT), (42, [PAD, PAD], LIN),
        (76, [PAD, PAD], E_SHIFT), (90, [PAD + 171, PAD], LIN), (100, [PAD + 171, PAD], None)]))))
    ind += 1
    symbol = add(layer(ind, "Symbol", transform(p=(0, 8), s=(64, 64)), parent=shift))
    ind += 1
    wordmark = add(layer(ind, "Wordmark", transform(p=anim([
        (0, [88, 0], LIN), (72, [88, 0], E_IN), (79, [68, 0], LIN), (100, [68, 0], None)])), parent=shift))

    # Orbit: a stroke that draws, undraws and shrinks into the dot (supporting graphic, not part of the mark)
    end_pct, n = 11, frame(11)
    trim_s, trim_e = [], []
    for f in range(int(n) + 1):
        p = min(f / n, 1)
        dash = 100 - 200 * cubic(E_ORBIT, p)
        trim_s.append({"t": f, "s": [max(0, -dash)], "o": {"x": [0], "y": [0]}, "i": {"x": [1], "y": [1]}})
        trim_e.append({"t": f, "s": [min(100, 100 - dash)], "o": {"x": [0], "y": [0]}, "i": {"x": [1], "y": [1]}})
    orbit_items = [
        {"ty": "el", "nm": "Ring", "p": static([0, 0]), "s": static([48, 48]), "d": 1},
        {"ty": "tm", "nm": "Trim", "s": {"a": 1, "k": trim_s}, "e": {"a": 1, "k": trim_e}, "o": static(0), "m": 1},
        {"ty": "st", "nm": "Stroke", "c": static(rgba(sym)), "o": static(100), "w": static(5), "lc": 2, "lj": 2},
        {"ty": "tr", "p": static([0, 0]), "a": static([0, 0]), "s": static([100, 100]), "r": static(0), "o": static(100)},
    ]
    ind += 1
    add(layer(ind, "Orbit", transform(
        p=(79, 50),
        r=anim([(0, [-30], E_ORBIT), (end_pct, [270], None)]),  # CSS -120deg..180deg, +90 for Lottie's 12 o'clock start
        s=anim([(0, [115, 115], E_ORBIT), (end_pct, [30, 30], None)]),
        o=anim([(0, [100], LIN), (end_pct, [100], LIN), (11.5, [0], LIN), (100, [0], None)])),
        [{"ty": "gr", "nm": "Orbit", "it": orbit_items}], parent=symbol))

    def form(name, rect, start, land, out_start, out_end, dx, dy):
        x, y, w, h, r = rect
        cx, cy = x + w / 2, y + h / 2
        off, home = [cx + dx, cy + dy], [cx, cy]
        return layer(0, name, transform(
            a=(cx, cy),
            p=anim([(0, off, LIN), (start, off, E_OUT), (land, home, LIN), (out_start, home, E_IN), (out_end, off, LIN), (100, off, None)]),
            o=anim([(0, [0], LIN), (start, [0], E_OUT), (land, [100], LIN), (out_start, [100], E_IN), (out_end, [0], LIN), (100, [0], None)])),
            group(name, [{"ty": "rc", "nm": name, "p": static([cx, cy]), "s": static([w, h]), "r": static(r), "d": 1}], sym),
            parent=symbol)

    forms = [
        form("Anchor top", RECTS["anchor-top"], 16, 24, 81, 86, 0, 16),
        form("Anchor bottom", RECTS["anchor-bottom"], 16, 24, 81, 86, 0, -16),
        form("Terminal top", RECTS["terminal-top"], 20, 28, 78, 83, -18, 0),
        form("Signal pill", RECTS["signal-pill"], 12, 20, 84, 89, 18, 0),
        form("Terminal bottom", RECTS["terminal-bottom"], 20, 28, 78, 83, -18, 0),
    ]
    dcx, dcy, dr = DOT
    forms.append(layer(0, "Signal dot", transform(
        a=(dcx, dcy), p=(dcx, dcy),
        s=anim([(0, [0, 0], LIN), (8, [0, 0], E_OUT), (13, [100, 100], LIN), (90, [100, 100], E_IN), (96, [0, 0], LIN), (100, [0, 0], None)])),
        group("Signal dot", [{"ty": "el", "nm": "Dot", "p": static([dcx, dcy]), "s": static([dr * 2, dr * 2]), "d": 1}], sym),
        parent=symbol))
    for f in forms:
        ind += 1; f["ind"] = ind; add(f)

    for li, d in enumerate(LETTERS):
        delay = li * 2.2
        a, b = 30 + delay, 40 + delay
        items = [{"ty": "sh", "nm": f"Path {k + 1}", "ks": static(s), "d": 1} for k, s in enumerate(parse_path(d))]
        ind += 1
        add(layer(ind, f"Letter {li + 1}", transform(
            p=anim([(0, [0, 12], LIN), (a, [0, 12], E_OUT), (b, [0, 0], LIN), (100, [0, 0], None)]),
            o=anim([(0, [0], LIN), (a, [0], E_OUT), (b, [100], LIN), (72, [100], E_IN), (79, [0], LIN), (100, [0], None)])),
            group(f"Letter {li + 1}", items, wm), parent=wordmark))

    return {"v": "5.7.4", "fr": FPS, "ip": 0, "op": OP, "w": W, "h": H, "nm": "BearStack Signal trace",
            "ddd": 0, "assets": [], "layers": layers, "markers": []}


def trim(anim_, op, name):
    """Cut the timeline at `op`; every value there is the finished lockup (the exit starts at 72%)."""
    anim_ = json.loads(json.dumps(anim_))
    anim_["op"], anim_["nm"] = op, name
    for lyr in anim_["layers"]:
        lyr["op"] = op
    return anim_


def dotlottie(path, anim_id, data, loop):
    manifest = {"version": "1", "generator": "BearStack make_lottie.py", "author": "BearStack",
                "animations": [{"id": anim_id, "speed": 1, "loop": loop, "autoplay": True}]}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr(f"animations/{anim_id}.json", json.dumps(data, separators=(",", ":")))


if __name__ == "__main__":
    import os
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(f"{out}/lottie", exist_ok=True)
    os.makedirs(f"{out}/dotlottie", exist_ok=True)
    for name, sym, wm in [("bone", BONE, BONE), ("primary", ORANGE, ESPRESSO), ("espresso", ESPRESSO, ESPRESSO)]:
        loop = build(sym, wm)
        intro = trim(loop, INTRO_OP, "BearStack Signal trace intro")
        for kind, data, loops in [("loop", loop, True), ("intro", intro, False)]:
            base = f"bearstack-signal-trace-{kind}-{name}"
            with open(f"{out}/lottie/{base}.json", "w") as fh:
                json.dump(data, fh, separators=(",", ":"))
            dotlottie(f"{out}/dotlottie/{base}.lottie", base, data, loops)
        print("wrote", name)
