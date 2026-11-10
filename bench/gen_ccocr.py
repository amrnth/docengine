"""Score a run on CC-OCR's table-parsing subsets (gen2: photo/scan x English/Chinese, 75 images each) with TEDS and
TEDS-S, using the IBM TEDS implementation vendored in OmniDocBench (vendor/OmniDocBench/src/metrics/table_metric.py).

  .venv-omni/bin/python bench/gen_ccocr.py results/modal_c3b_gen2 [results/modal_v2_gen2 ...]

Prediction = every HTML table in the page's markdown (markdown pipe tables converted to HTML), joined; ground truth =
CC-OCR's HTML answer. Both sides normalised the same way (th -> td, thead/tbody/tfoot dropped, attributes other than
colspan/rowspan dropped, inline formatting tags dropped). A page with no table scores 0.
"""
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "vendor", "OmniDocBench", "src", "metrics"))
from table_metric import TEDS  # noqa: E402

GT = json.load(open(os.path.join(ROOT, "data", "ccocr", "gt.json")))


def md_tables_to_html(md):
    out, rows = [], []
    for line in md.splitlines() + [""]:
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                rows.append(cells)
        elif rows:
            out.append("<table>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
                       + "</table>")
            rows = []
    return out


def norm(h):
    h = re.sub(r"<(/?)th\b", r"<\1td", h, flags=re.I)
    h = re.sub(r"</?(thead|tbody|tfoot|b|strong|i|em|u|sup|sub|span|br|p|div)\b[^>]*>", " ", h, flags=re.I)
    h = re.sub(r"<(td|tr|table)\b([^>]*)>",
               lambda m: "<" + m.group(1) + "".join(f' {a}="{v}"' for a, v in re.findall(
                   r'(colspan|rowspan)\s*=\s*"?(\d+)"?', m.group(2), re.I)) + ">", h, flags=re.I)
    return re.sub(r"\s+", " ", h)


def tables(md):
    found = re.findall(r"<table\b.*?</table>", md, re.S | re.I)
    return found or md_tables_to_html(md)


def score_one(args):
    name, md = args
    pred = tables(md)
    if not pred:
        return name, 0.0, 0.0
    p = "<html><body>" + norm("".join(pred)) + "</body></html>"
    g = "<html><body>" + norm(GT[name]["answer"]) + "</body></html>"
    return name, TEDS(structure_only=False).evaluate(p, g), TEDS(structure_only=True).evaluate(p, g)


def main(run):
    jobs = []
    for name in GT:
        if not name.startswith("table_"):
            continue
        path = os.path.join(run, "ccocr", os.path.splitext(name)[0] + ".md")
        jobs.append((name, open(path, encoding="utf-8").read() if os.path.exists(path) else ""))
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(score_one, jobs, chunksize=4))
    subsets = {}
    for name, t, ts in res:
        subsets.setdefault(name.split("/")[0], []).append((t, ts))
    summary = {k: {"n": len(v), "teds": round(100 * sum(x[0] for x in v) / len(v), 2),
                   "teds_s": round(100 * sum(x[1] for x in v) / len(v), 2)} for k, v in sorted(subsets.items())}
    allv = [x for v in subsets.values() for x in v]
    summary["all"] = {"n": len(allv), "teds": round(100 * sum(x[0] for x in allv) / len(allv), 2),
                      "teds_s": round(100 * sum(x[1] for x in allv) / len(allv), 2)}
    json.dump({"summary": summary, "per_image": {n: [t, ts] for n, t, ts in res}},
              open(os.path.join(run, "_ccocr_score.json"), "w"), indent=1)
    print(run)
    for k, v in summary.items():
        print(f"  {k:22s} n={v['n']:3d}  TEDS {v['teds']:6.2f}  TEDS-S {v['teds_s']:6.2f}")


if __name__ == "__main__":
    for r in sys.argv[1:]:
        main(r)
