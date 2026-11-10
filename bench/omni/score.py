"""Score results/<key>/ (OmniDocBench markdown) with the official end2end eval (CDM omitted) and compare runs.

  .venv-omni/bin/python bench/omni/score.py omni_plain omni_mask

Text / table / formula / reading-order numbers are the official metrics. "Overall*" substitutes formula
(1 - edit distance) for CDM, because CDM needs TeX Live + ImageMagick; it is NOT comparable to the leaderboard's
Overall, only between our own runs.
"""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OMNI = os.path.join(ROOT, "vendor", "OmniDocBench")
GT = os.path.abspath(os.environ["OMNI_GT"]) if os.environ.get("OMNI_GT") else os.path.join(ROOT, "data", "omnidocbench", "OmniDocBench.json")


def score(key):
    out = os.path.join(ROOT, "results", key, "_omni_metrics.json")
    if not os.path.exists(out):
        cfg = f"/tmp/omni_{key}.yaml"
        with open(cfg, "w") as f:
            f.write(subprocess.check_output([os.path.join(ROOT, "bench/omni/make_config.sh"), GT,
                                             os.path.join(ROOT, "results", key)], text=True))
        log = os.path.join(ROOT, "results", key, "_omni_eval.log")
        with open(log, "w") as lf:
            subprocess.run([sys.executable, "pdf_validation.py", "--config", cfg], cwd=OMNI, stdout=lf,
                           stderr=subprocess.STDOUT, check=True)
        shutil.copy(os.path.join(OMNI, "result", f"{key}_quick_match_metric_result.json"), out)
    m = json.load(open(out))
    text = m["text_block"]["all"]["Edit_dist"]["ALL_page_avg"]
    formula = m["display_formula"]["all"]["Edit_dist"]["ALL_page_avg"]
    teds = m["table"]["all"]["TEDS"]["all"]
    teds_s = m["table"]["all"]["TEDS_structure_only"]["all"]
    order = m["reading_order"]["all"]["Edit_dist"]["ALL_page_avg"]
    overall = ((1 - text) * 100 + teds * 100 + (1 - formula) * 100) / 3
    return {"run": key, "text_edit↓": round(text, 4), "formula_edit↓": round(formula, 4), "table_TEDS↑": round(teds * 100, 2),
            "table_TEDS_struct↑": round(teds_s * 100, 2), "order_edit↓": round(order, 4), "overall*↑": round(overall, 2)}


def main():
    rows = [score(k) for k in sys.argv[1:]]
    hdr = list(rows[0])
    print("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr))
    for r in rows:
        print("| " + " | ".join(str(r[h]) for h in hdr) + " |")
    json.dump(rows, open(os.path.join(ROOT, "results", "omni_scoreboard.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
