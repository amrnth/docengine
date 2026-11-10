"""Per-page consensus selection (minimum Bayes risk) between several readers' outputs: no labels, no categories.

  .venv/bin/python bench/consensus.py <out_key> runA runB runC ... [--plain-names] [--pool runX ...]

For every page, each candidate's output is compared with every other run's output (`--pool` adds extra runs that
vote but are never picked). Similarity = 1 - normalised edit distance on the page text with markup stripped
(HTML tags, markdown symbols, LaTeX commands, whitespace), so formatting conventions (HTML vs markdown tables, $ vs
\\( ) don't count, content does. The candidate with the highest mean similarity to the others is kept; ties go
to the first run listed. Writes results/<out_key>/ and _consensus.jsonl.
"""
import argparse
import json
import os
import re
import shutil

from rapidfuzz.distance import Levenshtein

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = re.compile(r"<[^>]+>")
LATEX_CMD = re.compile(r"\\[a-zA-Z]+")
NON_WORD = re.compile(r"[^\w]+", re.U)


def norm(md: str) -> str:
    t = TAG.sub(" ", md)
    t = LATEX_CMD.sub(" ", t)
    t = NON_WORD.sub(" ", t)
    return " ".join(t.lower().split())


def md_path(key, rel, plain):
    return os.path.join(ROOT, "results", key, rel + ("" if plain else "_pg1_repeat1") + ".md")


def pages_of(key, plain):
    base = os.path.join(ROOT, "results", key)
    out = []
    for dp, _, fs in os.walk(base):
        for f in fs:
            if f.endswith(".md") and not f.startswith("_"):
                rel = os.path.relpath(os.path.join(dp, f), base)[:-3]
                out.append(rel if plain else rel[: -len("_pg1_repeat1")])
    return out


def sim(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return Levenshtein.normalized_similarity(a, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--pool", nargs="*", default=[])
    ap.add_argument("--plain-names", action="store_true")
    args = ap.parse_args()
    plain = args.plain_names
    voters = args.runs + args.pool
    picks = {k: 0 for k in args.runs}
    log = []
    for rel in sorted(pages_of(args.runs[0], plain)):
        texts = {}
        for k in voters:
            p = md_path(k, rel, plain)
            texts[k] = norm(open(p, encoding="utf-8").read()) if os.path.exists(p) else ""
        scores = {}
        for k in args.runs:
            others = [o for o in voters if o != k]
            scores[k] = sum(sim(texts[k], texts[o]) for o in others) / len(others)
        best = max(args.runs, key=lambda k: (scores[k], -args.runs.index(k)))
        picks[best] += 1
        dst = md_path(args.out, rel, plain)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(md_path(best, rel, plain), dst)
        log.append({"page": rel, "pick": best, **{k: round(v, 4) for k, v in scores.items()}})
    with open(os.path.join(ROOT, "results", args.out, "_consensus.jsonl"), "w") as f:
        f.writelines(json.dumps(x) + "\n" for x in log)
    print(f"{args.out}: {sum(picks.values())} pages, picks {picks}")


if __name__ == "__main__":
    main()
