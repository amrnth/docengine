"""Reference-free check of a run on the random Common Crawl pages (data/random_cc), no benchmark ground truth.

  .venv/bin/python bench/random_eval.py results/modal_c3b_rcc

Born-digital pages carry their own text layer (what the author's software printed). Against it we measure, per page,
word-level recall (how much of the printed text we kept) and precision (how much of our text is really on the page:
low precision = invented text). Order-free bag of words, case-folded, markup stripped. Margins dropped by design
lower recall a little. Scanned pages (no usable layer) are listed for manual grading instead.
Also scores stage 1 alone (LightOnOCR-3 reading every page, from _pages.jsonl) for comparison, and flags
degenerate outputs (empty, repetition loops).
Writes <run>/_random_eval.json.
"""
import collections
import json
import os
import re
import sys

import pypdfium2 as pdfium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "data", "random_cc", "pages")
sys.path.insert(0, ROOT)
from docengine.pipeline import blocks_of  # noqa: E402

WORD = re.compile(r"\w+", re.U)


def words(s):
    s = re.sub(r"<[^>]+>|\\[a-zA-Z]+|[$*#_^{}|]", " ", s)
    return collections.Counter(w.lower() for w in WORD.findall(s) if len(w) > 1 or w.isdigit())


def layer(f):
    pdf = pdfium.PdfDocument(os.path.join(PAGES, f))
    t = pdf[0].get_textpage().get_text_range()
    pdf.close()
    return t


def pr(ref, hyp):
    inter = sum((ref & hyp).values())
    r = inter / max(1, sum(ref.values()))
    p = inter / max(1, sum(hyp.values()))
    return p, r


def loop(md):
    lines = [l for l in md.splitlines() if len(re.sub(r"<[^>]*>|[|:\-\s]", "", l)) > 25]  # long text lines only: table cells repeat legitimately
    return len(lines) > 20 and max(collections.Counter(lines).values()) > 10


def main(run):
    stage1 = {}
    p1 = os.path.join(run, "_pages.jsonl")
    if os.path.exists(p1):
        for d in map(json.loads, open(p1)):
            b = blocks_of("lighton", d.get("raw", ""))
            stage1[d["page"]] = "\n\n".join(t for _, _, t in b) if b else d.get("raw", "")
    rows, scanned = [], []
    for f in sorted(os.listdir(PAGES)):
        mdp = os.path.join(run, f[:-4] + ".md")
        md = open(mdp, encoding="utf-8").read() if os.path.exists(mdp) else ""
        L = words(layer(f))
        H = words(md)
        row = {"file": f, "md_chars": len(md), "empty": not md.strip(), "loop": loop(md),
               "layer_words": sum(L.values())}
        if sum(L.values()) < 30 or sum(L.values()) < 0.3 * sum(H.values()):
            row["scanned"] = True
            scanned.append(f)
        else:
            row["scanned"] = False
            row["precision"], row["recall"] = pr(L, H)
            if f in stage1:
                row["s1_precision"], row["s1_recall"] = pr(L, words(stage1[f]))
        rows.append(row)
    dig = [r for r in rows if not r["scanned"]]

    def mean(k, rs):
        v = [r[k] for r in rs if k in r]
        return round(100 * sum(v) / max(1, len(v)), 1)
    summary = {"pages": len(rows), "born_digital": len(dig), "scanned_or_image": len(scanned),
               "empty_outputs": sum(r["empty"] for r in rows), "loops": sum(r["loop"] for r in rows),
               "precision": mean("precision", dig), "recall": mean("recall", dig),
               "stage1_precision": mean("s1_precision", dig), "stage1_recall": mean("s1_recall", dig),
               "pages_recall_lt_80": sum(r.get("recall", 1) < 0.8 for r in dig),
               "pages_precision_lt_90": sum(r.get("precision", 1) < 0.9 for r in dig)}
    json.dump({"summary": summary, "pages": rows}, open(os.path.join(run, "_random_eval.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))
    worst = sorted(dig, key=lambda r: min(r["precision"], r["recall"]))[:12]
    for r in worst:
        print(f"  {r['file'][:50]:50s} P {r['precision']:.2f} R {r['recall']:.2f}  words {r['layer_words']}")


if __name__ == "__main__":
    main(sys.argv[1])
