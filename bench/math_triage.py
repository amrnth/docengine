"""Triage failed olmOCR-Bench math tests: is our formula the same maths written differently, or really wrong/missing?

  .venv/bin/python bench/math_triage.py modal_c3b_olmocr

The benchmark renders both formulas with KaTeX and compares the pictures, so LaTeX synonyms that draw different glyphs
(\\notin vs \\not\\in, \\leqslant vs \\leq, \\bar vs \\overline) or a formula split into several inline pieces fail.
This script normalises such synonyms on both sides (for triage only, never applied to our output) and buckets:
  same_math    a formula in our output equals the test formula after normalisation
  split        the test formula equals several consecutive inline formulas of ours joined (granularity only)
  close        best normalised match >= 0.85 (small real difference: a symbol, sub/superscript, missing term)
  wrong        a formula is there but differs more
  missing      no formula of ours is remotely similar (>= 0.5)
Writes failures/review/math_triage.jsonl.
"""
import json
import os
import re
import sys

from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYN = [(r"\\not\s*\\in\b", r"\\notin"), (r"\\leqslant", r"\\leq"), (r"\\geqslant", r"\\geq"), (r"\\le\b", r"\\leq"),
       (r"\\ge\b", r"\\geq"), (r"\\vert\b", "|"), (r"\\Vert\b", r"\\|"), (r"\\lvert|\\rvert", "|"),
       (r"\\lVert|\\rVert", r"\\|"), (r"\\overline\b", r"\\bar"), (r"\\widehat\b", r"\\hat"), (r"\\widetilde\b", r"\\tilde"),
       (r"\\overrightarrow\b", r"\\vec"), (r"\\ldots|\\dots|\\cdots|\.\.\.", r"\\dots"), (r"\\rm\b|\\mathrm\b|\\operatorname\b|\\text\b|\\textrm\b|\\mathit\b", ""),
       (r"\\left\b|\\right\b|\\big[lr]?\b|\\Big[lr]?\b|\\bigg[lr]?\b|\\Bigg[lr]?\b", ""), (r"\\[,;:!]|\\quad|\\qquad|~|\\ ", ""),
       (r"\\tag\{[^{}]*(\{[^{}]*\}[^{}]*)*\}", ""), (r"\\label\{[^}]*\}", ""), (r"\\displaystyle|\\nonumber|\\notag", ""),
       (r"\\varepsilon", r"\\epsilon"), (r"\\varphi", r"\\phi"), (r"\\Pr\b|\\P\b", "P"), (r"\\mathbf\{(\w)\}", r"\1"),
       (r"\\boldsymbol\{(\w)\}", r"\1"), (r"\\bm\{(\w)\}", r"\1"), (r"\\(begin|end)\{(aligned|align\*?|split|array|gathered|cases|matrix|pmatrix|bmatrix)\}(\{[lcr|]*\})?", ""),
       (r"&|\\\\", ""), (r"\\underset\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{\\(arg\s*max|arg\s*min|max|min|lim|sup|inf)\}", r"\\\2_{\1}"),
       (r"\\arg\s*\\?max", "argmax"), (r"\\arg\s*\\?min", "argmin"), (r"\\mathrm\{d\}|\\rm\{d\}", "d"), (r"\{\}", "")]


def norm(s):
    s = s.strip().strip("$").strip()
    for a, b in SYN:
        s = re.sub(a, b, s)
    s = re.sub(r"\{(\w)\}", r"\1", s)  # x_{i} == x_i
    s = re.sub(r"\s+", "", s)
    return s.rstrip(".,;")


def formulas(md):
    """(position, latex) of every formula in our markdown, display and inline, in order."""
    out = []
    for m in re.finditer(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\$([^$\n]+?)\$|\\\((.+?)\\\)", md, re.S):
        out.append((m.start(), m.end(), next(g for g in m.groups() if g is not None)))
    return out


def triage(md, want):
    w = norm(want)
    fs = formulas(md)
    best = 0.0
    for _, _, f in fs:
        n = norm(f)
        if n == w:
            return "same_math", 100.0
        best = max(best, fuzz.ratio(n, w))
    # split: consecutive formulas separated only by punctuation/short words
    for i in range(len(fs)):
        acc, end = norm(fs[i][2]), fs[i][1]
        for j in range(i + 1, min(i + 8, len(fs))):
            gap = md[end:fs[j][0]]
            if len(gap) > 12:
                break
            acc += re.sub(r"\s+|and|,|;|\.", "", gap) + norm(fs[j][2])
            end = fs[j][1]
            if fuzz.ratio(acc, w.replace(",", "")) >= 95 or acc == w:
                return "split", 100.0
            if len(acc) > len(w) * 1.3:
                break
    if best >= 85:
        return "close", best
    return ("wrong" if best >= 50 else "missing"), best


def main(run):
    rows = [json.loads(l) for l in open(os.path.join(ROOT, "results", run, "_failures.jsonl"))]
    out, counts = [], {}
    for r in rows:
        if r["type"] != "math":
            continue
        p = os.path.join(ROOT, "results", run, r["pdf"][:-4] + "_pg1_repeat1.md")
        md = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        b, s = triage(md, r["math"])
        counts.setdefault((r["category"], b), 0)
        counts[(r["category"], b)] += 1
        out.append({"pdf": r["pdf"], "id": r["id"], "bucket": b, "score": round(s, 1), "math": r["math"]})
    os.makedirs(os.path.join(ROOT, "failures", "review"), exist_ok=True)
    with open(os.path.join(ROOT, "failures", "review", "math_triage.jsonl"), "w") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    for k in sorted(counts):
        print(k, counts[k])


if __name__ == "__main__":
    main(sys.argv[1])
