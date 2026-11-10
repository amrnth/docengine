"""Read a very dense page in pieces ("tiles") instead of in one go.

A reader answers a whole page in one response, so a page with more text than its output limit (LightOnOCR-3:
12,288 tokens ~ 5,000 words; Infinity-Parser2: 16,384 ~ 9,000) is truncated, and small print is read at the
page-level resolution. Tiling fixes both: the page is cut into a few crops in reading order, each crop is rendered at
a higher resolution and read separately, and the results are joined.

Tiles come from the layout model's regions (PP-DocLayoutV3, already computed for every page, in reading order):
consecutive regions in the same column are grouped while the group stays below `max_frac` of the page area; a single
region larger than that is cut into horizontal bands at blank rows. Without layout regions the page is cut into
horizontal bands. Margin regions (headers, footers, page numbers) are left out unless keep_margins.
"""
import asyncio

from PIL import Image

from docengine.layout import DROP_LABELS

TILE_DPI = 400


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _inside(b, r):
    x0, y0, x1, y1 = max(b[0], r[0]), max(b[1], r[1]), min(b[2], r[2]), min(b[3], r[3])
    return max(0, x1 - x0) * max(0, y1 - y0) / max(1e-6, _area(b))


def _xoverlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    return max(0.0, w) / max(1e-6, min(a[2] - a[0], b[2] - b[0]))


def _ycover(children, box):
    """Share of box's height covered by the union of the children's vertical extents."""
    iv = sorted((max(c[1], box[1]), min(c[3], box[3])) for c in children)
    tot, cur0, cur1 = 0.0, None, None
    for a, b in iv:
        if b <= a:
            continue
        if cur1 is None or a > cur1:
            tot += (cur1 - cur0) if cur1 is not None else 0
            cur0, cur1 = a, b
        else:
            cur1 = max(cur1, b)
    tot += (cur1 - cur0) if cur1 is not None else 0
    return tot / max(1e-6, box[3] - box[1])


def _band_cuts(gray: Image.Image, box, n):
    """n-1 cut rows inside box (pixel coords of `gray`), each at the emptiest row near an even split."""
    x0, y0, x1, y1 = [int(v) for v in box]
    crop = gray.crop((x0, y0, x1, y1))
    w, h = crop.size
    px = crop.load()
    ink = [sum(255 - px[x, y] for x in range(0, w, 2)) for y in range(h)]
    cuts = []
    for k in range(1, n):
        target = k * h // n
        lo, hi = max(1, target - h // (3 * n)), min(h - 1, target + h // (3 * n))
        best = min(range(lo, hi), key=lambda y: (ink[y], abs(y - target))) if hi > lo else target
        cuts.append(y0 + best)
    return cuts


def make_tiles(regions, size, gray: Image.Image | None = None, keep_margins=True, max_frac=0.25):
    """regions: [[order, label, score, [x0,y0,x1,y1]], ...] in pixels of an image of `size` (W, H).
    Returns tile boxes in the same pixels, in reading order."""
    W, H = size
    max_area = max_frac * W * H
    regs = [r for r in sorted(regions, key=lambda r: r[0]) if keep_margins or r[1] not in DROP_LABELS]
    boxes = [list(map(float, r[3])) for r in regs]
    # Containers (a region holding >= 2 others, e.g. 'reference' around 'reference_content'): read the children when
    # they cover the container, otherwise the container itself. On dense pages the layout model often finds only a few
    # lines inside a big block, and reading just those would skip everything between them.
    inner = {i: [j for j, c in enumerate(boxes) if j != i and _inside(c, b) > 0.8] for i, b in enumerate(boxes)}
    drop = set()
    for i, b in enumerate(boxes):
        if len(inner[i]) < 2:
            continue
        if _ycover([boxes[j] for j in inner[i]], b) >= 0.7:
            drop.add(i)
        else:
            drop.update(inner[i])
    keep = []
    for i, b in enumerate(boxes):
        dup = any(j < i and j not in drop and _inside(b, c) > 0.9 and _inside(c, b) > 0.9 for j, c in enumerate(boxes))
        if i not in drop and not dup:
            keep.append(b)
    if not keep:
        keep = [[0.0, 0.0, float(W), float(H)]]
    tiles, cur = [], None
    for b in keep:
        if cur is None:
            cur = b
            continue
        u = _union(cur, b)
        if _xoverlap(cur, b) >= 0.5 and _area(u) <= max_area and b[1] >= cur[1] - 0.02 * H:
            cur = u
        else:
            tiles.append(cur)
            cur = b
    tiles.append(cur)
    out = []
    for t in tiles:  # a single block bigger than a tile: cut into bands at blank rows
        n = int(_area(t) // max_area) + 1
        if n > 1 and gray is not None:
            ys = [t[1]] + _band_cuts(gray, t, n) + [t[3]]
            out += [[t[0], a, t[2], b] for a, b in zip(ys, ys[1:]) if b - a > 4]
        elif n > 1:
            step = (t[3] - t[1]) / n
            out += [[t[0], t[1] + k * step, t[2], t[1] + (k + 1) * step] for k in range(n)]
        else:
            out.append(t)
    return out


async def read_tiled(rec, client, page_img: Image.Image, layout_size, regions, sem, keep_margins=True, max_frac=0.25,
                     pad=12):
    """Read `page_img` (rendered at any resolution) tile by tile. `regions` are in pixels of an image of
    `layout_size`. Returns (markdown, info) with info aggregated over tiles: finish is 'stop' only if every tile
    finished, mean_lp is token-weighted, raw is the joined markdown and tiles holds each tile's raw output."""
    W, H = layout_size
    sx, sy = page_img.width / W, page_img.height / H
    gray = page_img.convert("L").resize((int(W), int(H))) if regions is not None else None
    boxes = make_tiles(regions or [], (W, H), gray, keep_margins, max_frac)

    async def one(b):
        x0, y0 = max(0, b[0] * sx - pad), max(0, b[1] * sy - pad)
        x1, y1 = min(page_img.width, b[2] * sx + pad), min(page_img.height, b[3] * sy + pad)
        info = {}
        async with sem:
            md = await rec(client, page_img.crop((int(x0), int(y0), int(x1), int(y1))), info=info)
        return md, info

    results = await asyncio.gather(*(one(b) for b in boxes))
    mds = [m for m, _ in results if m and m.strip()]
    infos = [i for _, i in results]
    n_tok = sum(i.get("n_tok") or 0 for i in infos)
    lp = sum((i.get("mean_lp") or 0) * (i.get("n_tok") or 0) for i in infos)
    info = {"raw": "\n\n".join(mds), "tiles": [i.get("raw", "") for i in infos], "tile_boxes": boxes,
            "finish": "stop" if all(i.get("finish") == "stop" for i in infos) else "length",
            "n_tok": n_tok, "mean_lp": lp / n_tok if n_tok else None, "attempt": max((i.get("attempt", 0) for i in infos), default=0)}
    return "\n\n".join(mds), info
