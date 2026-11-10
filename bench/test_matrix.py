"""Per-test pass/fail of every olmOCR-Bench test for one run, in a fixed test order.

  .venv/bin/python bench/test_matrix.py modal_c3b_olmocr lt4_u ...

Writes reports/audit/pass/<key>.json (list of 0/1, aligned with reports/audit/tests.json) so that runs can be
compared test by test (paired statistics, "which systems fail this test", scores on a subset of tests).
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from failures import ROOT, all_tests  # noqa: E402

OUT = os.path.join(ROOT, "reports", "audit")


def tests_flat():
    """Every test, in a fixed order (load_tests returns a different order on each call)."""
    return [(cat, t) for cat, ts in all_tests() for t in sorted(ts, key=lambda t: t.id)]


def main(keys):
    os.makedirs(os.path.join(OUT, "pass"), exist_ok=True)
    flat = tests_flat()
    meta = []
    for cat, t in flat:
        meta.append({"id": t.id, "category": cat, "type": t.type, "pdf": t.pdf})
    tmp = os.path.join(OUT, f"tests.{os.getpid()}.tmp")
    json.dump(meta, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, os.path.join(OUT, "tests.json"))
    for key in keys:
        def one(ct):
            _, t = ct
            md = os.path.join(ROOT, "results", key, os.path.splitext(t.pdf)[0] + f"_pg{t.page}_repeat1.md")
            content = open(md, encoding="utf-8").read() if os.path.exists(md) else ""
            try:
                ok, _ = t.run(content)
            except Exception:  # noqa: BLE001
                ok = False
            return int(bool(ok))

        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(one, flat))
        json.dump(res, open(os.path.join(OUT, "pass", key + ".json"), "w"))
        cats = {}
        for (cat, _), r in zip(flat, res):
            cats.setdefault(cat, []).append(r)
        overall = sum(sum(v) / len(v) for v in cats.values()) / len(cats)
        print(f"{key}: {100 * overall:.1f}  ({sum(res)}/{len(res)} tests)", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
