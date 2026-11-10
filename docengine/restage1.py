"""Reuse a finished run's stage 1 for a new run: copy its reader outputs and layout, rebuild the stage-1 markdown.

Stage 1 (LightOnOCR-3-0.8B over every page + PP-DocLayoutV3) is the most expensive GPU step and does not change when
only later stages change. Its raw outputs are saved in _pages.jsonl, so the markdown it wrote can be rebuilt exactly
(same grounding_to_md call as docengine.pipeline in plain mode with --layout-drop).

  python -m docengine.restage1 --from-dir out/old_run --run-dir out/new_run --pdf-dir .../pdfs [--plain-names]
"""
import argparse
import json
import os
import shutil

from docengine.layout import DROP_LABELS
from docengine.pipeline import grounding_to_md
from docengine.reread import default_size, md_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--plain-names", action="store_true")
    ap.add_argument("--drop-margins", dest="keep_margins", action="store_false",
                    help="drop page headers/footers/page numbers/side notes (the olmOCR-Bench convention; "
                         "default since 2026-11-09: keep them)")
    ap.add_argument("--keep-margins", dest="keep_margins", action="store_true", help=argparse.SUPPRESS)  # old flag
    ap.set_defaults(keep_margins=True)
    args = ap.parse_args()
    os.makedirs(args.run_dir, exist_ok=True)
    for f in ("_pages.jsonl", "_layout.jsonl", "_run_stats.json"):
        if os.path.exists(os.path.join(args.from_dir, f)):
            shutil.copy(os.path.join(args.from_dir, f), os.path.join(args.run_dir, f))
    margins = {}
    for line in open(os.path.join(args.run_dir, "_layout.jsonl")):
        d = json.loads(line)
        margins[d["pdf"]] = [] if args.keep_margins else [r[3] for r in d["regions"] if r[1] in DROP_LABELS]
    n = 0
    for line in open(os.path.join(args.run_dir, "_pages.jsonl")):
        d = json.loads(line)
        rel = d["page"]
        md = grounding_to_md(d.get("raw", ""), margins=margins.get(rel, ()),
                             size=default_size(os.path.join(args.pdf_dir, rel)), reader="lighton",
                             keep_margins=args.keep_margins)
        out = md_path(args.run_dir, rel, args.plain_names)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
        n += 1
    t = {"stage1_reused_from": os.path.basename(args.from_dir.rstrip("/"))}
    src_t = os.path.join(args.from_dir, "_timing.json")
    if os.path.exists(src_t):
        old = json.load(open(src_t))
        t.update({k: old[k] for k in ("gpu12", "lt08_load_seconds", "stage1_seconds") if k in old})
    json.dump(t, open(os.path.join(args.run_dir, "_timing.json"), "w"), indent=2)
    print(f"stage 1 of {args.from_dir} reused: {n} pages", flush=True)


if __name__ == "__main__":
    main()
