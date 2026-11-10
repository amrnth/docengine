"""Crops for eye-checking failed math tests: the page region of the block holding our closest formula.

  .venv/bin/python bench/math_crops.py modal_c3b_olmocr <seed> <n> [buckets=close,wrong,missing]

Samples n failures from failures/review/math_triage.jsonl, finds our closest formula in the final-stage reader output,
crops its block from the page (150 dpi), and writes failures/review/crops/math_<k>.png plus a numbered contact sheet
failures/review/math_sheet_<seed>.png. Prints test LaTeX vs ours for each k.
"""
import json
import os
import random
import sys

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bench"))
from docengine.pipeline import blocks_of  # noqa: E402
from math_triage import formulas, norm  # noqa: E402

PDFS = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")


def load(run, name):
    p = os.path.join(ROOT, "results", run, name)
    return {d["page"]: d for d in map(json.loads, open(p))} if os.path.exists(p) else {}


def main(run, seed, n, buckets="close,wrong,missing"):
    rows = [json.loads(l) for l in open(os.path.join(ROOT, "failures", "review", "math_triage.jsonl"))]
    rows = [r for r in rows if r["bucket"] in buckets.split(",")]
    random.Random(int(seed)).shuffle(rows)
    stages = [("infinity", load(run, "_reread_pro.jsonl")), ("lighton", load(run, "_reread_lt4.jsonl")),
              ("lighton", load(run, "_pages.jsonl"))]
    tiles, k = [], 0
    for r in rows[:int(n)]:
        md = open(os.path.join(ROOT, "results", run, r["pdf"][:-4] + "_pg1_repeat1.md"), encoding="utf-8").read()
        w = norm(r["math"])
        fs = formulas(md)
        ours = max(fs, key=lambda f: fuzz.ratio(norm(f[2]), w))[2].strip() if fs else ""
        reader, d = next(((rd, s[r["pdf"]]) for rd, s in stages if r["pdf"] in s and s[r["pdf"]].get("raw")), (None, None))
        box = [0, 0, 1000, 1000]
        if d and ours:
            bl = blocks_of(reader, d["raw"])
            if bl:
                box = max(bl, key=lambda b: fuzz.partial_ratio(ours[:120], b[2]))[1]
        pdf = pdfium.PdfDocument(os.path.join(PDFS, r["pdf"]))
        img = pdf[0].render(scale=150 / 72).to_pil().convert("RGB")
        pdf.close()
        W, H = img.size
        c = img.crop((max(0, box[0] * W / 1000 - 30), max(0, box[1] * H / 1000 - 20),
                      min(W, box[2] * W / 1000 + 30), min(H, box[3] * H / 1000 + 20)))
        if c.width > 1100:
            c = c.resize((1100, int(c.height * 1100 / c.width)))
        c = c.crop((0, 0, c.width, min(c.height, 420)))
        ImageDraw.Draw(c).rectangle([0, 0, 44, 26], fill=(255, 255, 0))
        ImageDraw.Draw(c).text((4, 2), str(k), fill=(0, 0, 0), font_size=22)
        tiles.append(c)
        print(f"[{k}] {r['bucket']} {r['pdf']}\n   TEST: {r['math'][:230]}\n   OURS: {ours[:230]}")
        k += 1
    Hs = sum(t.height + 8 for t in tiles)
    sheet = Image.new("RGB", (1100, Hs), "white")
    y = 0
    for t in tiles:
        sheet.paste(t, (0, y))
        y += t.height + 8
    sheet.save(os.path.join(ROOT, "failures", "review", f"math_sheet_{seed}.png"))


if __name__ == "__main__":
    main(*sys.argv[1:])
