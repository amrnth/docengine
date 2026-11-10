"""Numbers for the olmOCR-Bench audit: wrong tests, tests nobody passes, scores without the wrong tests, paired tests.

  .venv/bin/python bench/audit_report.py

Inputs (all in reports/audit/): tests.json + pass/<run>.json (bench/test_matrix.py), wrong_tests.jsonl
(bench/audit_confirm.py), review.json (the by-eye verdict on every candidate). Writes summary.json and prints tables.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_tests import OUT  # noqa: E402

CATS = ["arxiv_math", "old_scans_math", "table_tests", "old_scans", "headers_footers", "multi_column", "long_tiny_text", "baseline"]
SINGLE = ["lt4_u", "lt08_u", "inf_pro", "inf_flash", "olm2_plain", "ovisocr2"]
NAMES = {"modal_c3b_olmocr": "docengine c3b (cascade)", "modal_c3b2_olmocr": "docengine c3b2 (cascade)", "casc20": "casc20 (0.8B -> 4B)",
         "lt4_u": "LightOnOCR-3-4B", "lt08_u": "LightOnOCR-3-0.8B", "inf_pro": "Infinity-Parser2-Pro",
         "inf_flash": "Infinity-Parser2-Flash", "olm2_plain": "olmOCR-2", "ovisocr2": "OvisOCR2", "v2": "docengine v2",
         "pipe_mask": "docengine v1"}


def score(p, cat, keep):
    return 100 * np.mean([p[(cat == c) & keep].mean() for c in CATS])


def paired(pa, pb, cat, keep, pdf, n=5000, seed=0):
    """Difference a - b in overall score. Bootstrap over PAGES inside each category (tests of one page move together)."""
    rng = np.random.default_rng(seed)
    groups = []
    for c in CATS:
        idx = np.where((cat == c) & keep)[0]
        pages, inv = np.unique(pdf[idx], return_inverse=True)
        # per-page sums of (a, b, count)
        sa = np.bincount(inv, weights=pa[idx], minlength=len(pages))
        sb = np.bincount(inv, weights=pb[idx], minlength=len(pages))
        cn = np.bincount(inv, minlength=len(pages)).astype(float)
        groups.append((sa, sb, cn))
    diffs = np.empty(n)
    for k in range(n):
        d = 0.0
        for sa, sb, cn in groups:
            pick = rng.integers(0, len(cn), len(cn))
            tot = cn[pick].sum()
            d += (sa[pick].sum() - sb[pick].sum()) / tot
        diffs[k] = 100 * d / len(CATS)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p = 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return float(np.mean(diffs)), float(lo), float(hi), float(min(1.0, p))


def main():
    tests = json.load(open(os.path.join(OUT, "tests.json")))
    cat = np.array([t["category"] for t in tests])
    pdf = np.array([t["pdf"] for t in tests])
    ids = [t["id"] for t in tests]
    P = {r[:-5]: np.array(json.load(open(os.path.join(OUT, "pass", r))), dtype=float) for r in sorted(os.listdir(os.path.join(OUT, "pass")))}
    review = json.load(open(os.path.join(OUT, "review.json")))
    cand = [json.loads(l) for l in open(os.path.join(OUT, "wrong_tests.jsonl"))]
    rule = {r["id"] for r in cand if r["confirmed"]}
    wrong = (rule - set(review["rejected"])) | set(review["headers_footers_wrong"])
    missing = wrong - set(ids)
    assert not missing, missing
    keep = np.array([i not in wrong for i in ids])
    S = {"n_tests": len(tests), "n_text_tests_checkable": sum(1 for l in open(os.path.join(OUT, "text_audit.jsonl"))
                                                               if json.loads(l)["verdict"] in ("on_page", "not_on_page")),
         "rule_candidates": len(rule), "rejected_by_eye": len(review["rejected"]), "wrong_text_tests": len(rule - set(review["rejected"])),
         "wrong_header_footer_tests": len(review["headers_footers_wrong"]), "wrong_total": len(wrong)}
    S["wrong_by_category"] = {c: int(((cat == c) & ~keep).sum()) for c in CATS if ((cat == c) & ~keep).any()}
    S["points_locked_by_wrong_tests"] = round(sum(100 * ((cat == c) & ~keep).sum() / (cat == c).sum() for c in CATS) / len(CATS), 2)
    S["wrong_tests_passed_by"] = {r: int(P[r][~keep].sum()) for r in P}
    anyp = np.max(np.stack([P[r] for r in P]), axis=0)
    S["failed_by_every_run"] = {c: [int(((cat == c) & (anyp == 0)).sum()), int((cat == c).sum())] for c in CATS}
    S["failed_by_every_run_total"] = int((anyp == 0).sum())
    S["best_of_all_runs_per_test"] = round(score(anyp, cat, np.ones(len(tests), bool)), 1)
    S["best_of_all_runs_per_test_clean"] = round(score(anyp, cat, keep), 1)
    allk = np.ones(len(tests), bool)
    S["scores"] = {r: {"full": round(score(P[r], cat, allk), 1), "clean": round(score(P[r], cat, keep), 1)} for r in P}
    a = "modal_c3b_olmocr"
    S["paired_vs_c3b"] = {}
    for b in ["lt4_u", "inf_pro", "lt08_u", "inf_flash", "olm2_plain", "casc20", "modal_c3b2_olmocr"]:
        d, lo, hi, p = paired(P[a], P[b], cat, allk, pdf)
        S["paired_vs_c3b"][b] = {"diff": round(d, 2), "ci95": [round(lo, 2), round(hi, 2)], "p": round(p, 4)}
    json.dump(S, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    npass = {i: int(sum(P[r][k] for r in P)) for k, i in enumerate(ids)}
    L = ["# olmOCR-Bench tests that a faithful reader cannot pass (%d)" % len(wrong), "",
         "Made by `bench/audit_report.py`. Rule: `bench/audit_tests.py` + `bench/audit_confirm.py`; by-eye verdicts: `review.json`;",
         "page crops: `crops/`. \"Runs that pass\" is out of %d saved runs." % len(P), "",
         "## Text tests: the expected string is not what the page says (%d)" % S["wrong_text_tests"], "",
         "| test id | max_diffs | the test expects | the page says | edits | runs that pass |", "|---|---|---|---|---|---|"]
    for r in cand:
        if r["confirmed"] and r["id"] in wrong:
            for p in r["parts"]:
                if p.get("confirmed"):
                    L.append("| `%s` | %d | %s | %s | %d | %d |" % (r["id"], r["max_diffs"], p["want"].replace("|", "\\|"),
                                                              p["nearest"].replace("|", "\\|"), p["dist"], npass[r["id"]]))
    L += ["", "\"The page says\" is the PDF's stored text (lower case, accents removed), also output by at least 3 of 4 model families.", "",
          "## Header/footer tests: the forbidden string is also body text (%d)" % S["wrong_header_footer_tests"], "",
          "| test id | why | runs that pass |", "|---|---|---|"]
    for i, why in review["headers_footers_wrong"].items():
        L.append("| `%s` | %s | %d |" % (i, why, npass[i]))
    L += ["", "## Candidates of the rule that we did not count (%d)" % len(review["rejected"]), "", "| test id | why |", "|---|---|"]
    for i, why in review["rejected"].items():
        L.append("| `%s` | %s |" % (i, why))
    open(os.path.join(OUT, "wrong_tests.md"), "w").write("\n".join(L) + "\n")
    print(json.dumps({k: v for k, v in S.items() if k not in ("scores", "paired_vs_c3b")}, indent=1))
    print("\n| system | full benchmark | without the %d wrong tests |\n|---|---|---|" % len(wrong))
    for r, v in sorted(S["scores"].items(), key=lambda kv: -kv[1]["full"]):
        print(f"| {NAMES.get(r, r)} | {v['full']} | {v['clean']} |")
    print("\n| c3b minus ... | difference | 95% CI (pages resampled) | p |\n|---|---|---|---|")
    for b, v in S["paired_vs_c3b"].items():
        print(f"| {NAMES.get(b, b)} | {v['diff']:+.2f} | {v['ci95'][0]:+.2f} to {v['ci95'][1]:+.2f} | {v['p']} |")


if __name__ == "__main__":
    main()
