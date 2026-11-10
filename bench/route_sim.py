"""Simulate confidence routing on olmOCR-Bench: read every page with run A, re-read the least-confident X% with run B.

  .venv/bin/python bench/route_sim.py lt08 pipe_mask [--feature mean_lp]

Confidence comes only from A's own output (results/<A>/_pages.jsonl: token logprobs, finish reason), never from the
benchmark category or tests. Reports the overall score at fixed re-read fractions (no threshold tuned on the bench).
"""
import argparse, json, os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from failures import all_tests  # noqa: E402
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def confidence(info, feature):
    if info.get("finish") != "stop":
        return -1e9
    if feature == "mean_lp":
        return info.get("mean_lp") or 0.0
    if feature == "low_frac":
        return -(info.get("n_low", 0) / max(1, info.get("n_tok", 1)))
    if feature == "low_count":
        return -info.get("n_low", 0)
    if feature == "min_lp":
        return info.get("min_lp") or 0.0
    raise ValueError(feature)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--feature", default="mean_lp")
    args = ap.parse_args()
    failed = {k: {json.loads(l)["id"] for l in open(os.path.join(ROOT, "results", k, "_failures.jsonl"))} for k in (args.a, args.b)}
    infos = {}
    for l in open(os.path.join(ROOT, "results", args.a, "_pages.jsonl")):
        d = json.loads(l); infos[d["page"]] = d
    order = sorted(infos, key=lambda p: confidence(infos[p], args.feature))  # least confident first
    cats = all_tests()
    print(f"feature={args.feature}  | reread% | overall | " + " | ".join(c for c, _ in cats))
    for frac in (0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0):
        reread = set(order[: int(round(frac * len(order)))])
        row = []
        for cat, tests in cats:
            ok = sum(t.id not in failed[args.b if t.pdf in reread else args.a] for t in tests)
            row.append(100 * ok / len(tests))
        print(f"| {frac*100:4.0f}% | {sum(row)/len(row):.1f} | " + " | ".join(f"{x:.1f}" for x in row))


if __name__ == "__main__":
    main()
