"""List every failed olmOCR-Bench test for one run, for error analysis.

  .venv/bin/python bench/failures.py pipe_mask [ovisocr2 ...]

Writes results/<key>/_failures.jsonl (one row per failed test, with the scorer's explanation) and prints a
category x test-type table of failure counts. Baseline tests are run too.
"""

import glob
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from olmocr.bench.tests import BaselineTest, load_tests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data")


def all_tests():
    """(category, tests) per JSONL, plus the auto 'baseline' group benchmark.py adds for PDFs without one."""
    groups = [(os.path.basename(jl)[:-6], load_tests(jl)) for jl in sorted(glob.glob(os.path.join(BENCH, "*.jsonl")))]
    pdfs = sorted({t.pdf for _, ts in groups for t in ts})
    has = {t.pdf for _, ts in groups for t in ts if t.type == "baseline"}
    groups.append(("baseline", [BaselineTest(id=f"{p}_baseline", pdf=p, page=1, type="baseline") for p in pdfs if p not in has]))
    return groups


def run(key):
    fails, totals = [], Counter()
    for cat, tests in all_tests():

        def one(t):
            md = os.path.join(ROOT, "results", key, os.path.splitext(t.pdf)[0] + f"_pg{t.page}_repeat1.md")
            content = open(md, encoding="utf-8").read() if os.path.exists(md) else ""
            try:
                ok, why = t.run(content)
            except Exception as e:  # noqa: BLE001
                ok, why = False, f"error: {e}"
            return t, ok, why

        with ThreadPoolExecutor(8) as ex:
            for t, ok, why in ex.map(one, tests):
                totals[(cat, t.type)] += 1
                if not ok:
                    row = {k: v for k, v in vars(t).items() if isinstance(v, (str, int, float, bool, type(None), list))}
                    row.update(category=cat, explanation=str(why)[:500])
                    fails.append(row)
    with open(os.path.join(ROOT, "results", key, "_failures.jsonl"), "w") as f:
        for r in fails:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    fc = Counter((r["category"], r["type"]) for r in fails)
    print(f"\n{key}: {len(fails)} failed of {sum(totals.values())}")
    print(f"{'category':16} {'type':10} {'fail':>5} {'total':>6} {'pass%':>6}")
    for (c, ty), n in sorted(totals.items()):
        print(f"{c:16} {ty:10} {fc[(c, ty)]:5} {n:6} {100 * (1 - fc[(c, ty)] / n):6.1f}")


if __name__ == "__main__":
    for k in sys.argv[1:]:
        run(k)
