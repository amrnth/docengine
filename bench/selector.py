"""Per-page selection between two readers using only their own confidence (no labels, no categories).

  .venv/bin/python bench/selector.py <out_key> <runA> <runB> --calib <calibA> <calibB> [--plain-names] [--margin 0.0]

Each run directory needs _pages.jsonl (token logprob stats per page, written by docengine.pipeline). A page's
confidence in a run is its mean token logprob (pages that did not finish, i.e. loops/truncation, rank lowest). It is
turned into a percentile against a *calibration* run of the same reader on different documents (we calibrate on the
other benchmark), so the two readers' scales become comparable without touching the benchmark being scored.
The page goes to B only if B's percentile beats A's by more than --margin; A is the default.
Writes results/<out_key>/ (markdown copied from the chosen run) and _select.jsonl.
"""
import argparse
import bisect
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(key):
    return {d["page"]: d for d in map(json.loads, open(os.path.join(ROOT, "results", key, "_pages.jsonl")))}


def conf(info):
    if info is None or info.get("finish") != "stop" or info.get("mean_lp") is None:
        return -1e9
    return info["mean_lp"]


def percentile_fn(calib_key):
    vals = sorted(conf(d) for d in load(calib_key).values())
    return lambda x: bisect.bisect_right(vals, x) / len(vals)


def md_path(key, page, plain):
    return os.path.join(ROOT, "results", key, os.path.splitext(page)[0] + ("" if plain else "_pg1_repeat1") + ".md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--calib", nargs=2, required=True)
    ap.add_argument("--plain-names", action="store_true")
    ap.add_argument("--margin", type=float, default=0.0)
    args = ap.parse_args()
    A, B = load(args.a), load(args.b)
    pa, pb = percentile_fn(args.calib[0]), percentile_fn(args.calib[1])
    out_dir = os.path.join(ROOT, "results", args.out)
    os.makedirs(out_dir, exist_ok=True)
    n_b = 0
    with open(os.path.join(out_dir, "_select.jsonl"), "w") as log:
        for page in sorted(set(A) | set(B)):
            qa, qb = pa(conf(A.get(page))), pb(conf(B.get(page)))
            pick = args.b if qb > qa + args.margin else args.a
            n_b += pick == args.b
            dst = md_path(args.out, page, args.plain_names)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(md_path(pick, page, args.plain_names), dst)
            log.write(json.dumps({"page": page, "pick": pick, "pa": round(qa, 4), "pb": round(qb, 4)}) + "\n")
    print(f"{args.out}: {len(set(A) | set(B))} pages, {n_b} from {args.b}")


if __name__ == "__main__":
    main()
