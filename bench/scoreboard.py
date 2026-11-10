"""Score every results/<model_key>/ candidate with the official olmOCR-Bench scorer and build the scoreboard.

  python bench/scoreboard.py [model_key ...]      # default: every folder in results/

Writes results/<key>/_score.txt (raw scorer output) and results/scoreboard.md / scoreboard.json.
Cost per 1k pages = GPU $/hr (as charged by RunPod for that pod) x inference hours / pages x 1000.
"""

import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data")
RESULTS = os.path.join(ROOT, "results")
CATS = ["arxiv_math", "old_scans_math", "table_tests", "old_scans", "headers_footers", "multi_column", "long_tiny_text", "baseline"]


def score(key):
    out_txt = os.path.join(RESULTS, key, "_score.txt")
    if os.path.exists(out_txt) and os.path.getmtime(out_txt) > os.path.getmtime(os.path.join(RESULTS, key)):
        return open(out_txt).read()
    link = os.path.join(BENCH, key)
    if os.path.islink(link) or os.path.exists(link):
        if os.path.islink(link):
            os.unlink(link)
        else:
            shutil.rmtree(link)
    os.symlink(os.path.join(RESULTS, key), link)
    r = subprocess.run([sys.executable, "-m", "olmocr.bench.benchmark", "--dir", BENCH, "--candidate", key],
                       capture_output=True, text=True, cwd=ROOT)
    text = r.stdout + r.stderr
    with open(out_txt, "w") as f:
        f.write(text)
    return text


def parse(text, key):
    row = {}
    m = re.search(rf"^{re.escape(key)}\s*: Average Score: ([\d.]+)% ± ([\d.]+)%", text, re.M)
    if m:
        row["overall"], row["ci"] = float(m.group(1)), float(m.group(2))
    else:
        m = re.search(rf"^{re.escape(key)}\s*: Average Score: ([\d.]+)%", text, re.M)
        row["overall"] = float(m.group(1)) if m else None
    for c in CATS:
        m = re.search(rf"^\s+{c}(?:\.jsonl)?\s*: ([\d.]+)% \(", text, re.M)
        row[c] = float(m.group(1)) if m else None
    return row


def cost(key):
    t = json.load(open(os.path.join(RESULTS, key, "_timing.json")))
    p = json.load(open(os.path.join(RESULTS, key, "_pod.json")))
    hrs = t["inference_seconds"] / 3600
    per_1k = float(p["cost_per_hr"]) * hrs / t["pages"] * 1000
    return {"gpu": t["gpu"], "cost_per_hr": p["cost_per_hr"], "seconds": t["inference_seconds"],
            "pages_per_sec": round(t["pages"] / t["inference_seconds"], 2), "usd_per_1k_pages": round(per_1k, 3)}


def main():
    keys = sys.argv[1:] or sorted(d for d in os.listdir(RESULTS) if os.path.isdir(os.path.join(RESULTS, d)))
    rows = []
    for k in keys:
        row = {"model": k, **parse(score(k), k)}
        try:
            row.update(cost(k))
        except FileNotFoundError:
            pass
        rows.append(row)
    json.dump(rows, open(os.path.join(RESULTS, "scoreboard.json"), "w"), indent=2)
    hdr = ["model", "overall", "ci", *CATS, "usd_per_1k_pages", "pages_per_sec", "gpu"]
    lines = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in sorted(rows, key=lambda r: -(r.get("overall") or 0)):
        lines.append("| " + " | ".join("" if r.get(h) is None else str(r.get(h)) for h in hdr) + " |")
    md = "\n".join(lines)
    open(os.path.join(RESULTS, "scoreboard.md"), "w").write(md + "\n")
    print(md)


if __name__ == "__main__":
    main()
