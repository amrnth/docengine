"""Second stage of the olmOCR-Bench text-test audit: confirm "the expected string is not what the page says".

  .venv/bin/python bench/audit_tests.py && .venv/bin/python bench/audit_confirm.py

Input: reports/audit/text_audit.jsonl (stage 1: expected string not found in the PDF's stored text) and the saved
outputs of six single models from four model families, read from pixels.

A test is CONFIRMED wrong when all three hold:
  1. its expected string is not in the stored text by the test's own rule, under any normalisation (stage 1);
  2. the stored text holds a close but different string (edit distance <= 35% of the length), and
  3. at least 3 of the 4 model families output that stored-text string (within the test's own max_diffs) and do not
     output the test's string.
So two kinds of independent evidence (the PDF's encoding, and several unrelated OCR models) agree with each other and
disagree with the test.

Writes reports/audit/wrong_tests.jsonl (every candidate, with `confirmed`). The rule gives candidates only: each one
is then checked by eye (bench/audit_crops.py, reports/audit/review.json). bench/audit_report.py writes the final list.
"""
import json
import os
import sys
import unicodedata

from fuzzysearch import find_near_matches

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_tests import OUT, strip_accents  # noqa: E402
from failures import ROOT  # noqa: E402

from olmocr.bench.tests import normalize_text  # noqa: E402

FAMILIES = {"LightOnOCR-3": ["lt4_u", "lt08_u"], "Infinity-Parser2": ["inf_pro", "inf_flash"],
            "olmOCR-2": ["olm2_plain"], "OvisOCR2": ["ovisocr2"]}
RUNS = [r for rs in FAMILIES.values() for r in rs]


def md_of(run, pdf, cache={}):
    k = (run, pdf)
    if k not in cache:
        p = os.path.join(ROOT, "results", run, os.path.splitext(pdf)[0] + "_pg1_repeat1.md")
        t = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        cache[k] = strip_accents(normalize_text(unicodedata.normalize("NFKC", t))).casefold()
    return cache[k]


def has(s, hay, k):
    return bool(s) and bool(find_near_matches(s, hay, max_l_dist=k))


def main():
    tests = json.load(open(os.path.join(OUT, "tests.json")))
    idx = {(t["category"], t["id"]): i for i, t in enumerate(tests)}
    passes = {r[:-5]: json.load(open(os.path.join(OUT, "pass", r))) for r in sorted(os.listdir(os.path.join(OUT, "pass")))}
    rows = [json.loads(l) for l in open(os.path.join(OUT, "text_audit.jsonl"))]
    out = []
    for r in rows:
        if r["verdict"] != "not_on_page":
            continue
        i = idx[(r["category"], r["id"])]
        r["passed_by"] = sorted(k for k, v in passes.items() if v[i])
        worst = None
        for p in r["parts"]:
            if p["found"] is not None:
                continue
            want = strip_accents(p["want"]).casefold()
            page = p["nearest"]
            close = p["dist"] <= max(4, min(25, int(0.35 * len(want))))
            fam_page, fam_test = [], []
            for fam, runs in FAMILIES.items():
                reads_page = any(has(page, md_of(run, r["pdf"]), r["max_diffs"]) for run in runs)
                reads_test = any(has(want, md_of(run, r["pdf"]), r["max_diffs"]) for run in runs)
                if reads_test:
                    fam_test.append(fam)
                elif reads_page:
                    fam_page.append(fam)
            p.update(close=close, families_read_page=fam_page, families_read_test=fam_test)
            p["confirmed"] = bool(close and len(fam_page) >= 3)
            if worst is None or p["confirmed"]:
                worst = p
        r["confirmed"] = any(p.get("confirmed") for p in r["parts"])
        out.append(r)
    with open(os.path.join(OUT, "wrong_tests.jsonl"), "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    conf = [r for r in out if r["confirmed"]]
    print(f"not in stored text: {len(out)}; confirmed by >=3 of 4 model families: {len(conf)}")
    import collections
    print("confirmed by category:", dict(collections.Counter(r["category"] for r in conf)))
    print("confirmed tests passed by N of", len(passes), "runs:", sorted(collections.Counter(len(r["passed_by"]) for r in conf).items()))


if __name__ == "__main__":
    main()
