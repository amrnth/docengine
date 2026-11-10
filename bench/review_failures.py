"""Print failed olmOCR-Bench tests of one run with the matching part of our output, for manual review.

  .venv/bin/python bench/review_failures.py modal_c3b_olmocr <category> [type]

For each failed test: what the test wants, and the closest stretch of our markdown (fuzzy alignment), so a human can
judge whether the failure is a real reading error or a test/convention artefact. Also renders the page to
failures/review/png/<pdf>.png (150 dpi) to look at.
"""
import json
import os
import sys

import pypdfium2 as pdfium
from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDFS = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")
PNG = os.path.join(ROOT, "failures", "review", "png")


def render(rel):
    out = os.path.join(PNG, rel.replace("/", "__")[:-4] + ".png")
    if not os.path.exists(out):
        os.makedirs(PNG, exist_ok=True)
        pdf = pdfium.PdfDocument(os.path.join(PDFS, rel))
        pdf[0].render(scale=150 / 72).to_pil().save(out)
        pdf.close()
    return out


def near(md, s, pad=60):
    if not s or not md:
        return ""
    a = fuzz.partial_ratio_alignment(s, md, processor=str.lower)
    lo, hi = max(0, a.dest_start - pad), min(len(md), a.dest_end + pad)
    return f"[{a.score:.0f}] …{md[lo:hi]}…".replace("\n", "⏎")


def main(run, cat, typ=None):
    rows = [json.loads(l) for l in open(os.path.join(ROOT, "results", run, "_failures.jsonl"))]
    rows = [r for r in rows if r["category"] == cat and (typ is None or r["type"] == typ)]
    by = {}
    for r in rows:
        by.setdefault(r["pdf"], []).append(r)
    for i, (pdf, rs) in enumerate(sorted(by.items())):
        md_path = os.path.join(ROOT, "results", run, pdf[:-4] + "_pg1_repeat1.md")
        md = open(md_path, encoding="utf-8").read() if os.path.exists(md_path) else ""
        render(pdf)
        print(f"\n=== [{i}] {pdf}  (md {len(md)} chars)")
        for r in rs:
            t = r["type"]
            if t == "math":
                print(f"  MATH  want: {r['math'][:160]}")
                print(f"        ours: {near(md, r['math'], 40)[:260]}")
            elif t == "order":
                print(f"  ORDER  {r['before'][:70]!r}  BEFORE  {r['after'][:70]!r}")
                print(f"        b: {near(md, r['before'], 0)[:110]}")
                print(f"        a: {near(md, r['after'], 0)[:110]}")
                ib = md.lower().find(r['before'][:25].lower())
                ia = md.lower().find(r['after'][:25].lower())
                print(f"        exact pos before={ib} after={ia}")
            elif t in ("present", "absent"):
                print(f"  {t.upper()} want: {r['text'][:160]!r}")
                print(f"        ours: {near(md, r['text'], 30)[:260]}")
            elif t == "table":
                nb = {k: r.get(k) for k in ("up", "down", "left", "right", "top_heading", "left_heading") if r.get(k)}
                print(f"  TABLE cell={r['cell']!r} {nb}")
                print(f"        {r['explanation'][:220]}")
            else:
                print(f"  {t}: {r['explanation'][:200]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
