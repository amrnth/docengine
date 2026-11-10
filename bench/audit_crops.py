"""Picture proof for the audit: crop the page where a confirmed-wrong test's string should be.

  .venv/bin/python bench/audit_crops.py

For each confirmed row of reports/audit/wrong_tests.jsonl, find the stored-text string on the page (pdfium text
search on a few words around the first difference), render that strip at 3x, and put the test's expected string
under it. Writes contact sheets reports/audit/crops/sheet_<k>.png (5 cases each, numbered in file order).
"""
import difflib
import json
import os
import sys
import textwrap

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_tests import OUT, PDFS, strip_accents  # noqa: E402

CROPS = os.path.join(OUT, "crops")


def font(size):
    for p in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def locate(tp, want, page_str):
    """Rect of a few words of the page's string, near the first place where it differs from the test's string."""
    w = strip_accents(want).casefold()
    sm = difflib.SequenceMatcher(None, w, page_str, autojunk=False)
    pos = next((j1 for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"), 0)
    words, spans, k = page_str.split(), [], 0
    for wd in words:
        k = page_str.index(wd, k)
        spans.append((k, wd))
        k += len(wd)
    order = sorted(range(len(spans)), key=lambda i: abs(spans[i][0] - pos))
    for n in (3, 2, 1):
        for i in order:
            piece = " ".join(wd for _, wd in spans[i:i + n])
            if len(piece) < 5:
                continue
            s = tp.search(piece, match_case=False)
            hit = s.get_next()
            if hit:
                idx, cnt = hit
                rects = [tp.get_rect(r) for r in range(tp.count_rects(idx, cnt))]
                if rects:
                    return rects
    return None


def main():
    os.makedirs(CROPS, exist_ok=True)
    rows = [json.loads(l) for l in open(os.path.join(OUT, "wrong_tests.jsonl"))]
    f1, f2 = font(22), font(17)
    tiles, n = [], 0
    for r in rows:
        if not r.get("confirmed"):
            continue
        for p in r["parts"]:
            if not p.get("confirmed"):
                continue
            pdf = pdfium.PdfDocument(os.path.join(PDFS, r["pdf"]))
            pg = pdf[0]
            W, H = pg.get_size()
            rects = locate(pg.get_textpage(), p["want"], p["nearest"])
            n += 1
            if not rects:
                print("not located:", r["id"])
                pdf.close()
                continue
            l = min(a[0] for a in rects); b = min(a[1] for a in rects); rr = max(a[2] for a in rects); t = max(a[3] for a in rects)
            cx = (l + rr) / 2
            x0, x1 = max(0, cx - 190), min(W, cx + 190)
            y0, y1 = max(0, b - 26), min(H, t + 26)
            sc = 3
            img = pg.render(scale=sc, crop=(x0, y0, W - x1, H - y1)).to_pil().convert("RGB")
            pdf.close()
            d = ImageDraw.Draw(img)
            # mark the located words
            d.rectangle([(l - x0) * sc - 3, (y1 - t) * sc - 3, (rr - x0) * sc + 3, (y1 - b) * sc + 3], outline=(220, 30, 30), width=3)
            cap = textwrap.wrap("TEST EXPECTS: " + p["want"], 110)[:3] + textwrap.wrap("STORED TEXT:  " + p["nearest"], 110)[:3]
            tile = Image.new("RGB", (max(img.width, 1140), img.height + 26 * len(cap) + 44), "white")
            tile.paste(img, (0, 0))
            dd = ImageDraw.Draw(tile)
            dd.text((6, img.height + 4), f"#{n}  {r['id']}  (max_diffs {r['max_diffs']}, {p['dist']} edits)", fill=(90, 90, 90), font=f2)
            for i, line in enumerate(cap):
                dd.text((6, img.height + 30 + 26 * i), line, fill=(180, 0, 0) if line.startswith("TEST") or (i < 3 and not line.startswith("STORED") and "STORED" not in "".join(cap[:i + 1])) else (0, 90, 0), font=f1)
            tiles.append(tile)
    per = 5
    for k in range(0, len(tiles), per):
        grp = tiles[k:k + per]
        sheet = Image.new("RGB", (max(t.width for t in grp), sum(t.height for t in grp) + 12 * len(grp)), (200, 200, 200))
        y = 0
        for t in grp:
            sheet.paste(t, (0, y))
            y += t.height + 12
        sheet.save(os.path.join(CROPS, f"sheet_{k // per + 1}.png"))
    print(len(tiles), "crops")


if __name__ == "__main__":
    main()
