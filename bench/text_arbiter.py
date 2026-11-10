"""For failed text tests (present / order) on born-digital pages, ask the PDF's own text layer who is right:
the test's expected string or the matching stretch of our output.

  .venv/bin/python bench/text_arbiter.py modal_c3b_olmocr

For each failed string, align it with our markdown (fuzzy) to get "ours", then compare both with the page's embedded
text (pdfium, whitespace collapsed, lower-case). Verdicts:
  gt_wrong     ours matches the text layer clearly better than the test string (test typo / wrong GT)
  ours_wrong   the test string matches the text layer clearly better (real reading error by us)
  both_ok      both match about equally (formatting difference: spaces, LaTeX for symbols, line breaks)
  no_layer     scanned page, no usable text layer (needs eyes)
Writes failures/review/text_arbiter.jsonl and prints counts per category/test type.
"""
import collections
import json
import os
import re
import sys

import pypdfium2 as pdfium
from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDFS = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")


def layer(rel, cache={}):
    if rel not in cache:
        pdf = pdfium.PdfDocument(os.path.join(PDFS, rel))
        t = pdf[0].get_textpage().get_text_range()
        pdf.close()
        cache[rel] = re.sub(r"\s+", " ", t.replace("￾", "").replace("\x02", "")).lower()
    return cache[rel]


def clean(s):
    s = re.sub(r"\$+|\\[a-zA-Z]+|[{}_^*#]", " ", s)  # strip markdown/LaTeX markup for comparison
    return re.sub(r"\s+", " ", s).strip().lower()


def main(run):
    rows = [json.loads(l) for l in open(os.path.join(ROOT, "results", run, "_failures.jsonl"))]
    out, cnt = [], collections.Counter()
    for r in rows:
        keys = {"present": ["text"], "order": ["before", "after"]}.get(r["type"])
        if not keys:
            continue
        md = open(os.path.join(ROOT, "results", run, r["pdf"][:-4] + "_pg1_repeat1.md"), encoding="utf-8").read()
        L = layer(r["pdf"])
        verdicts = []
        for k in keys:
            want = r[k]
            a = fuzz.partial_ratio_alignment(want.lower(), md.lower())
            ours = md[a.dest_start:a.dest_end]
            if len(L) < 0.3 * len(clean(md)) or len(L) < 50:
                verdicts.append(("no_layer", want, ours, 0, 0))
                continue
            g = fuzz.partial_ratio(clean(want), L)
            o = fuzz.partial_ratio(clean(ours), L)
            v = "gt_wrong" if o - g >= 3 else "ours_wrong" if g - o >= 3 else "both_ok"
            verdicts.append((v, want, ours, g, o))
        # the test fails because of its worst string; report the most damning verdict
        order = ["ours_wrong", "gt_wrong", "both_ok", "no_layer"]
        v = min(verdicts, key=lambda x: order.index(x[0]))
        cnt[(r["category"], r["type"], v[0])] += 1
        out.append({"pdf": r["pdf"], "id": r["id"], "type": r["type"], "verdict": v[0], "want": v[1][:200],
                    "ours": v[2][:200], "gt_vs_layer": round(v[3]), "ours_vs_layer": round(v[4])})
    with open(os.path.join(ROOT, "failures", "review", "text_arbiter.jsonl"), "w") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    for k in sorted(cnt):
        print(k, cnt[k])


if __name__ == "__main__":
    main(sys.argv[1])
