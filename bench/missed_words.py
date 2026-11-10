"""Where on the page are the words a system misses? Attributes every missed text-layer word on the random web pages to
the layout region it sits in, to test the claim "our recall gap is mostly page headers/footers we drop by design".

  .venv/bin/python bench/missed_words.py modal_c3b2_rcc ext_reducto_r1_rcc ext_datalab_accurate_rcc

For each page the reference is the PDF text layer, tokenised exactly like bench/random_eval.py. A word missed m times
out of n occurrences gives each occurrence a weight m/n. Each occurrence is placed by its character boxes and assigned
the label of the smallest PP-DocLayoutV3 region (from our run's _layout.jsonl) containing its centre:

  margin   header / footer / number / aside_text: what c3b2 drops by default
  picture  image / chart / seal: text drawn inside pictures (logos, maps, screenshots)
  body     any other region (text, title, table, footnote, ...)
  none     outside every region

Pages: the born-digital pages common to all runs given (as in bench/external_compare.py). Writes
reports/external/missed_words.json.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

import pypdfium2 as pdfium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from docengine.layout import DROP_LABELS  # noqa: E402
from docengine.reread import default_size  # noqa: E402

PAGES = os.path.join(ROOT, "data", "random_cc", "pages")
R = os.path.join(ROOT, "results")
PICTURE = {"image", "chart", "seal"}
TOKEN = re.compile(r"\w+", re.U)
STRIP = re.compile(r"<[^>]+>|\\[a-zA-Z]+|[$*#_^{}|]")


def words(s):  # same as bench/random_eval.words
    s = STRIP.sub(" ", s)
    return Counter(w.lower() for w in TOKEN.findall(s) if len(w) > 1 or w.isdigit())


def layer_words(f):
    """[(word, (x, y) centre in layout pixels)] for the page's text layer, same tokens as words(layer text)."""
    path = os.path.join(PAGES, f)
    W, H = default_size(path)
    pdf = pdfium.PdfDocument(path)
    page = pdf[0]
    pw, ph = page.get_size()
    tp = page.get_textpage()
    text = tp.get_text_range()
    n = tp.count_chars()
    out = []
    # get_text_range returns one character per text-page char (pdfium), so indices line up; guard if not
    aligned = len(text) == n
    for m in TOKEN.finditer(STRIP.sub(lambda x: " " * len(x.group()), text)):
        w = m.group().lower()
        if not (len(w) > 1 or w.isdigit()):
            continue
        xs, ys = [], []
        if aligned:
            for i in range(m.start(), m.end()):
                l, b, r, t = tp.get_charbox(i)
                if r > l or t > b:
                    xs += [l, r]
                    ys += [b, t]
        if xs:
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            out.append((w, (cx * W / pw, (ph - cy) * H / ph)))
        else:
            out.append((w, None))
    pdf.close()
    return out


def label_at(pt, regions):
    if pt is None:
        return "none"
    best = None
    for _, lab, _, b in regions:
        if b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]:
            a = (b[2] - b[0]) * (b[3] - b[1])
            if best is None or a < best[0]:
                best = (a, lab)
    if best is None:
        return "none"
    lab = best[1]
    return "margin" if lab in DROP_LABELS else "picture" if lab in PICTURE else "body"


def ours_dropped(run, f):
    """For our pipeline: Counter of words in blocks the final stage's reader READ but our filters dropped, split into
    'margin' (header/footer/page number/aside, by the reader's own label or a layout margin region) and 'picture'
    (image/chart/figure blocks)."""
    from docengine.pipeline import GROUNDING_DROP, INFINITY_DROP, MARGIN_LABELS, _inside, blocks_of
    for name, reader in (("_reread_pro.jsonl", "infinity"), ("_reread_lt4.jsonl", "lighton"), ("_pages.jsonl", "lighton")):
        p = os.path.join(R, run, name)
        if not os.path.exists(p):
            continue
        d = next((x for x in map(json.loads, open(p)) if x["page"] == f), None)
        if d and d.get("raw") and not d.get("tiles"):
            break
    else:
        return {}
    W, H = default_size(os.path.join(PAGES, f))
    regions = [r[3] for r in _LAYOUT_CACHE.get(f, []) if r[1] in DROP_LABELS]
    drop = INFINITY_DROP if reader == "infinity" else GROUNDING_DROP
    out = {"margin": Counter(), "picture": Counter()}
    for lab, box, text in blocks_of(reader, d["raw"]):
        bb = [box[0] * W / 1000, box[1] * H / 1000, box[2] * W / 1000, box[3] * H / 1000]
        if lab in drop:
            kind = "margin" if (lab in MARGIN_LABELS or lab in ("page_footnote",)) else "picture"
        elif reader == "lighton" and any(_inside(bb, reg) >= 0.6 for reg in regions):
            kind = "margin"
        else:
            continue
        out[kind] += words(text)
    return out


_LAYOUT_CACHE = {}


def main(runs):
    evals = {r: {p["file"]: p for p in json.load(open(os.path.join(R, r, "_random_eval.json")))["pages"]} for r in runs}
    common = sorted(set.intersection(*({f for f, p in e.items() if not p["scanned"] and "precision" in p}
                                       for e in evals.values())))
    layout = {json.loads(l)["pdf"]: json.loads(l)["regions"] for l in open(os.path.join(R, runs[0], "_layout.jsonl"))}
    _LAYOUT_CACHE.update(layout)
    cats = ("margin", "picture", "body", "none")
    tot = {r: Counter() for r in runs}
    why = Counter()  # runs[0] (ours): missed words that were read and dropped vs never read
    why_pages = defaultdict(Counter)
    ref_by_cat = Counter()
    per_page = defaultdict(dict)
    for f in common:
        lw = layer_words(f)
        L = Counter(w for w, _ in lw)
        where = [(w, label_at(pt, layout.get(f, []))) for w, pt in lw]
        for _, c in where:
            ref_by_cat[c] += 1
        for r in runs:
            md_path = os.path.join(R, r, f[:-4] + ".md")
            O = words(open(md_path, encoding="utf-8").read()) if os.path.exists(md_path) else Counter()
            miss = Counter()
            missed_words = Counter()
            for w, c in where:
                m = max(0, L[w] - O.get(w, 0))
                if m:
                    miss[c] += m / L[w]
                    missed_words[w] = m
            tot[r] += miss
            if r == runs[0]:
                dropped = ours_dropped(r, f)
                for w, m in missed_words.items():
                    dm = min(m, dropped.get("margin", Counter()).get(w, 0))
                    dp = min(m - dm, dropped.get("picture", Counter()).get(w, 0))
                    for k, v in (("read, dropped as margin", dm), ("read, dropped as picture", dp),
                                 ("not read", m - dm - dp)):
                        why[k] += v
                        why_pages[f][k] += v
            per_page[f][r] = {c: round(miss[c], 1) for c in cats if miss[c]}
    n_ref = sum(ref_by_cat.values())
    res = {"pages": len(common), "reference_words": n_ref,
           "reference_words_by_region": dict(ref_by_cat), "runs": {}}
    print(f"{len(common)} born-digital pages, {n_ref} text-layer words "
          f"({', '.join(f'{c} {100 * ref_by_cat[c] / n_ref:.1f}%' for c in cats)})\n")
    print(f"{'run':32s} {'missed':>7s} " + " ".join(f"{c:>15s}" for c in cats) + "   recall all / without margin")
    for r in runs:
        m = tot[r]
        miss = sum(m.values())
        rec_all = 1 - miss / n_ref
        rec_nom = 1 - (miss - m["margin"]) / (n_ref - ref_by_cat["margin"])
        res["runs"][r] = {"missed": round(miss), "missed_by_region": {c: round(m[c]) for c in cats},
                          "recall_words_pooled": round(100 * rec_all, 1),
                          "recall_words_pooled_without_margin": round(100 * rec_nom, 1)}
        print(f"{r:32s} {miss:7.0f} " + " ".join(f"{m[c]:7.0f} ({100 * m[c] / miss:4.1f}%)" for c in cats)
              + f"   {100 * rec_all:5.1f} / {100 * rec_nom:5.1f}")
    tw = sum(why.values())
    print(f"\n{runs[0]}: of {tw:.0f} missed words, " + ", ".join(f"{k} {v:.0f} ({100 * v / tw:.1f}%)" for k, v in why.items()))
    res["ours_missed_why"] = {k: round(v) for k, v in why.items()}
    res["ours_missed_why_per_page"] = {f: dict(c) for f, c in why_pages.items()}
    res["per_page"] = per_page
    json.dump(res, open(os.path.join(ROOT, "reports", "external", "missed_words.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:])
