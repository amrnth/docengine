"""Score a run on the synthetic stress pages (bench/stress_gen.py) against their exact text.

  .venv/bin/python bench/stress_eval.py results/modal_c3b_stress

Per page and per stage (stage 1 LightOnOCR-3-0.8B, LightOnOCR-3-4B re-read, Infinity-Pro re-read, final):
  recall     share of ground-truth words we output (bag of words, case-folded)
  precision  share of our words that are in the ground truth
  char_sim   order-aware similarity of the whole text (normalised Levenshtein, markup stripped)
  finish     'length' = the reader hit its output-token cap (page truncated)
Prints a table by true font size x columns and writes <run>/_stress_eval.json.
"""
import collections
import json
import os
import re
import sys

from rapidfuzz.distance import Levenshtein

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from docengine.pipeline import blocks_of  # noqa: E402

GT = os.path.join(ROOT, "data", "stress", "gt")


def clean(s):
    s = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|[*#$|`]|\\[a-zA-Z]+|[{}^_]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def words(s):
    return collections.Counter(w.lower().strip(".,;:()\"'") for w in s.split() if w.strip(".,;:()\"'"))


def score(gt, hyp):
    g, h = words(gt), words(hyp)
    inter = sum((g & h).values())
    a, b = clean(gt), clean(hyp)
    return {"recall": inter / max(1, sum(g.values())), "precision": inter / max(1, sum(h.values())),
            "char_sim": Levenshtein.normalized_similarity(a, b), "out_words": sum(h.values())}


def load(run, name):
    p = os.path.join(run, name)
    return {d["page"]: d for d in map(json.loads, open(p))} if os.path.exists(p) else {}


def stage_text(reader, d):
    b = blocks_of(reader, d.get("raw", ""))
    return "\n".join(t for _, _, t in b) if b else d.get("raw", "")


def main(run):
    meta = [json.loads(l) for l in open(os.path.join(ROOT, "data", "stress", "meta.jsonl"))]
    st = {"s1": ("lighton", load(run, "_pages.jsonl")), "lt4": ("lighton", load(run, "_reread_lt4.jsonl")),
          "pro": ("infinity", load(run, "_reread_pro.jsonl"))}
    rows = []
    for m in meta:
        f = m["file"]
        gt = open(os.path.join(GT, f[:-4] + ".txt"), encoding="utf-8").read()
        md = open(os.path.join(run, f[:-4] + ".md"), encoding="utf-8").read()
        row = dict(m, final=score(gt, md))
        for k, (reader, d) in st.items():
            if f in d:
                row[k] = dict(score(gt, stage_text(reader, d[f])), finish=d[f].get("finish"),
                              n_tok=d[f].get("n_tok"))
        rows.append(row)
    json.dump(rows, open(os.path.join(run, "_stress_eval.json"), "w"), indent=1)
    print(f"{'page':24s} {'pt':>4s} {'words':>6s} | {'final R':>7s} {'P':>5s} {'sim':>5s} | s1 R  sim  fin  tok | reread")
    for r in sorted(rows, key=lambda r: (r["kind"], r["true_pt"], r["cols"])):
        f, s1 = r["final"], r.get("s1", {})
        rr = " ".join(f"{k}:{r[k]['recall']:.2f}/{r[k]['finish']}" for k in ("lt4", "pro") if k in r)
        print(f"{r['file'][:-4]:24s} {r['true_pt']:4.1f} {r['words']:6d} | {f['recall']:7.2f} {f['precision']:5.2f} "
              f"{f['char_sim']:5.2f} | {s1.get('recall', 0):.2f} {s1.get('char_sim', 0):.2f} {str(s1.get('finish'))[:4]:>4s} "
              f"{s1.get('n_tok') or 0:5d} | {rr}")


if __name__ == "__main__":
    main(sys.argv[1])
