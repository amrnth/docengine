"""Side-by-side tables for ours vs commercial APIs on our own test sets (stress pages, random web pages).

  .venv/bin/python bench/external_compare.py            # prints tables, writes reports/external/compare.json

Every system is scored on the *same* pages: for the web set, the born-digital pages every run agrees are born-digital
(random_eval's per-run 'scanned' flag depends on output length, so the sets can differ slightly). Run each run's
scorer first (bench/stress_eval.py, bench/random_eval.py).
"""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, "results")

STRESS = {"ours (c3b2 + fixes)": ["modal_c3b2c_stress"],
          "Reducto r-1": ["ext_reducto_r1_stress", "ext_reducto_r1_stress_r2"],
          "Datalab accurate": ["ext_datalab_accurate_stress", "ext_datalab_accurate_stress_r2"]}
WEB = {"ours (c3b2)": ["modal_c3b2_rcc"],
       "Reducto r-1": ["ext_reducto_r1_rcc", "ext_reducto_r1_rcc_r2"],
       "Datalab accurate": ["ext_datalab_accurate_rcc", "ext_datalab_accurate_rcc_r2"]}


def have(run, f):
    return os.path.exists(os.path.join(R, run, f))


def bucket(pt):
    for b in (3, 3.5, 4, 4.5, 5, 6):
        if pt < b + 0.25:
            return b
    return 7


def stress():
    out = {}
    for name, runs in STRESS.items():
        for run in runs:
            if not have(run, "_stress_eval.json"):
                continue
            rows = json.load(open(os.path.join(R, run, "_stress_eval.json")))
            g = defaultdict(list)
            for r in rows:
                g[f"{r['kind']} {bucket(r['true_pt'])}"].append(r["final"]["recall"])
            mean = {m: round(100 * sum(r["final"][m] for r in rows) / len(rows), 1)
                    for m in ("recall", "precision", "char_sim")}
            out[f"{name} [{run}]"] = {"pages": len(rows), **mean,
                                      "recall_by_bucket": {k: round(100 * sum(v) / len(v), 1) for k, v in sorted(g.items())}}
    return out


def web():
    data = {}
    for name, runs in WEB.items():
        for run in runs:
            if have(run, "_random_eval.json"):
                data[f"{name} [{run}]"] = {p["file"]: p for p in json.load(open(os.path.join(R, run, "_random_eval.json")))["pages"]}
    common = set.intersection(*({f for f, p in d.items() if not p["scanned"] and "precision" in p} for d in data.values()))
    out = {}
    for k, d in data.items():
        P = [d[f]["precision"] for f in common]
        Rc = [d[f]["recall"] for f in common]
        out[k] = {"pages": len(common), "precision": round(100 * sum(P) / len(P), 1),
                  "recall": round(100 * sum(Rc) / len(Rc), 1),
                  "pages_recall_lt_80": sum(r < 0.8 for r in Rc), "pages_precision_lt_90": sum(p < 0.9 for p in P),
                  "empty_outputs_all_200": sum(p["empty"] for p in d.values())}
    return out, sorted(common)


def main():
    s = stress()
    w, common = web()
    print("STRESS (54 pages, exact ground truth)")
    for k, v in s.items():
        print(f"  {k:60s} R {v['recall']:5.1f} P {v['precision']:5.1f} sim {v['char_sim']:5.1f}")
    keys = list(next(iter(s.values()))["recall_by_bucket"])
    print("  recall by bucket:", " | ".join(keys))
    for k, v in s.items():
        print(f"  {k[:40]:40s}", " ".join(f"{v['recall_by_bucket'].get(b, 0):5.1f}" for b in keys))
    print(f"\nWEB ({len(common)} born-digital pages common to every run)")
    for k, v in w.items():
        print(f"  {k:60s} P {v['precision']:5.1f} R {v['recall']:5.1f}  R<80: {v['pages_recall_lt_80']:3d}  "
              f"P<90: {v['pages_precision_lt_90']:3d}  empty: {v['empty_outputs_all_200']}")
    json.dump({"stress": s, "web": w, "web_common_pages": common},
              open(os.path.join(ROOT, "reports", "external", "compare.json"), "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
