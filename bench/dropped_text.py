"""Which failed text tests (present / order) were READ correctly but then THROWN AWAY by our own filtering?

  .venv/bin/python bench/dropped_text.py modal_c3b_olmocr

For each failed string, look at the reader output of the stage that produced the page's final markdown (Infinity-Pro
re-read > LightOnOCR-3-4B re-read > stage 1). If a block there contains the string (fuzzy >= 85) and that block's
label is one we drop (header/footer/page number/aside/image/figure...), the reading was right and our filter lost it.
Writes failures/review/dropped_text.jsonl and crops each block (with margin) to failures/review/crops/drop_<n>.png
for eye checks.
"""
import json
import os
import sys

import pypdfium2 as pdfium
from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from docengine.layout import DROP_LABELS  # noqa: E402
from docengine.pipeline import GROUNDING_DROP, INFINITY_DROP, _inside, blocks_of  # noqa: E402

PDFS = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")
CROPS = os.path.join(ROOT, "failures", "review", "crops")


def load(run, name):
    p = os.path.join(ROOT, "results", run, name)
    return {d["page"]: d for d in map(json.loads, open(p))} if os.path.exists(p) else {}


def crop(rel, box, out, pad=40):
    pdf = pdfium.PdfDocument(os.path.join(PDFS, rel))
    img = pdf[0].render(scale=150 / 72).to_pil().convert("RGB")
    pdf.close()
    W, H = img.size
    x0, y0, x1, y1 = box[0] * W / 1000 - pad, box[1] * H / 1000 - pad, box[2] * W / 1000 + pad, box[3] * H / 1000 + pad
    img.crop((max(0, x0), max(0, y0), min(W, x1), min(H, y1))).save(out)


def main(run):
    stages = [("infinity", load(run, "_reread_pro.jsonl")), ("lighton", load(run, "_reread_lt4.jsonl")),
              ("lighton", load(run, "_pages.jsonl"))]
    margins = {}
    for line in open(os.path.join(ROOT, "results", run, "_layout.jsonl")):
        d = json.loads(line)
        margins[d["pdf"]] = [(r[1], r[3]) for r in d["regions"] if r[1] in DROP_LABELS]
    sizes = {}

    def page_size(rel):
        if rel not in sizes:
            pdf = pdfium.PdfDocument(os.path.join(PDFS, rel))
            sizes[rel] = pdf[0].get_size()
            pdf.close()
        return sizes[rel]
    rows = [json.loads(l) for l in open(os.path.join(ROOT, "results", run, "_failures.jsonl"))]
    os.makedirs(CROPS, exist_ok=True)
    out, n = [], 0
    for r in rows:
        if r["type"] not in ("present", "order"):
            continue
        reader, d = next(((rd, s[r["pdf"]]) for rd, s in stages if r["pdf"] in s and s[r["pdf"]].get("raw")),
                         (None, None))
        if not d:
            continue
        blocks = blocks_of(reader, d["raw"])
        drop = INFINITY_DROP if reader == "infinity" else GROUNDING_DROP
        for key in ("text", "before", "after"):
            want = r.get(key)
            if not want:
                continue
            best = max(blocks, key=lambda b: fuzz.partial_ratio(want.lower(), b[2].lower()), default=None)
            if not best:
                continue
            s = fuzz.partial_ratio(want.lower(), best[2].lower())
            why = best[0] if best[0] in drop else None
            if s >= 85 and not why:
                W, H = page_size(r["pdf"])
                k = 2048 / max(W, H)
                bb = [best[1][0] * W * k / 1000, best[1][1] * H * k / 1000, best[1][2] * W * k / 1000, best[1][3] * H * k / 1000]
                hit = [lab for lab, reg in margins.get(r["pdf"], ()) if _inside(bb, reg) >= 0.6]
                why = f"layout:{hit[0]}" if hit else None
            if s >= 85 and why:
                path = os.path.join(CROPS, f"drop_{n}.png")
                crop(r["pdf"], best[1], path)
                out.append({"n": n, "pdf": r["pdf"], "id": r["id"], "cat": r["category"], "type": r["type"],
                            "want": want[:160], "label": why, "box": best[1], "reader": reader,
                            "block": best[2][:160]})
                n += 1
    with open(os.path.join(ROOT, "failures", "review", "dropped_text.jsonl"), "w") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(n, "failed strings were read but dropped by label")
    for o in out:
        print(f"[{o['n']}] {o['cat']}/{o['type']} label={o['label']} box={o['box']} :: {o['want'][:90]!r}")


if __name__ == "__main__":
    main(sys.argv[1])
