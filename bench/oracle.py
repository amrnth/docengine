"""Compare runs per olmOCR-Bench category and compute the per-page "oracle" ceiling.

  .venv/bin/python bench/oracle.py pipe_mask olm2_plain

Needs results/<key>/_failures.jsonl for every key (bench/failures.py). The oracle picks, for every page, the run
that passes the most tests on that page: the best any page-level router choosing between these runs could do.
Scores follow the official definition: per-JSONL pass rate, overall = mean over JSONL files.
"""

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from failures import all_tests  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data")


def main(keys):
    failed = {k: {json.loads(l)["id"] for l in open(os.path.join(ROOT, "results", k, "_failures.jsonl"))} for k in keys}
    cats = dict(all_tests())

    rows = {k: {} for k in keys + ["oracle"]}
    picks = defaultdict(int)
    for cat, tests in cats.items():
        by_page = defaultdict(list)
        for t in tests:
            by_page[(t.pdf, t.page)].append(t.id)
        for k in keys:
            rows[k][cat] = 100 * sum(t.id not in failed[k] for t in tests) / len(tests)
        passed = 0
        for page, ids in by_page.items():
            best = max(keys, key=lambda k: (sum(i not in failed[k] for i in ids), -keys.index(k)))
            picks[best] += 1
            passed += sum(i not in failed[best] for i in ids)
        rows["oracle"][cat] = 100 * passed / len(tests)

    names = list(cats)
    print("| run | overall | " + " | ".join(names) + " |\n|" + "---|" * (len(names) + 2))
    for k, r in rows.items():
        print(f"| {k} | {sum(r.values()) / len(r):.1f} | " + " | ".join(f"{r[c]:.1f}" for c in names) + " |")
    print("oracle page picks (ties go to the first run):", dict(picks))


if __name__ == "__main__":
    main(sys.argv[1:])
