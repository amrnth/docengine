"""Headline ParseBench numbers for our pipelines, read from the official per-category evaluation reports, next to the
official leaderboard (data/parsebench_lb/leaderboard.csv, fetched from run-llama/ParseBench).

  python bench/parsebench_summary.py docengine_c3b docengine_v2 ...

Per category, the leaderboard's default metric (parse_bench/analysis/aggregation_report.py _DEFAULT_METRICS):
tables = grits_trm_composite, charts = rule_pass_rate (chart data points), content faithfulness = content_faithfulness,
semantic formatting = semantic_formatting, visual grounding = layout_element_rule_pass_rate. Overall = mean of five.
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATS = [("Tables", "table", "grits_trm_composite"), ("Charts", "chart", "rule_pass_rate"),
        ("Content_Faithfulness", "text_content", "content_faithfulness"),
        ("Semantic_Formatting", "text_formatting", "semantic_formatting"),
        ("Visual_Grounding", "layout", "layout_element_rule_pass_rate")]
REF = ["LlamaParse Agentic Plus", "Upstage Document Parse 2 (Enhanced)", "Anthropic Opus 5.5", "LightOnOCR-3-4B",
       "LightOnOCR-3-0.8B", "Datalab Accurate", "Infinity-Parser2-Pro", "Reducto (Agentic)", "Chandra-ocr-2",
       "OvisOCR2"]


def ours(name):
    row = {"Provider": f"**{name}** (ours)"}
    vals = []
    for col, cat, metric in CATS:
        p = os.path.join(ROOT, "results", "parsebench", name, cat, "_evaluation_report.json")
        if not os.path.exists(p):
            row[col] = None
            continue
        m = json.load(open(p))["aggregate_metrics"].get("avg_" + metric)
        row[col] = None if m is None else 100 * m
        vals.append(row[col] or 0.0)
    row["Overall"] = sum(vals) / len(CATS) if len(vals) == len(CATS) else None
    return row


def main(names):
    lb = {r["Provider"]: r for r in csv.DictReader(open(os.path.join(ROOT, "data", "parsebench_lb", "leaderboard.csv")))}
    rows = [ours(n) for n in names] + [lb[n] for n in REF if n in lb]
    cols = ["Overall"] + [c for c, _, _ in CATS]
    fmt = lambda v: "—" if v in (None, "") else f"{float(v):.1f}"  # noqa: E731
    print("| Provider | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for r in rows:
        print(f"| {r['Provider']} | " + " | ".join(fmt(r.get(c)) for c in cols) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
