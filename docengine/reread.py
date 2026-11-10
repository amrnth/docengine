"""docengine v2, stage 2: re-read the least-confident pages of a v1 (mask) run with LightOnOCR-3-4B.

Stage 1 is `python -m docengine.pipeline --mode mask` with OvisOCR2, which writes every page's markdown plus
_pages.jsonl (OvisOCR2's token-logprob confidence) and _layout.jsonl (PP-DocLayoutV3 regions). This stage, run
against a vLLM server for LightOnOCR-3 (served as "lighton"), picks pages by OvisOCR2's own confidence only
(mean token logprob; pages that did not finish rank lowest) and overwrites their markdown with LightOnOCR's
grounding output, dropping margin blocks by LightOn's label or by the stage-1 layout margin regions.

  python -m docengine.reread --run-dir out/ --pdf-dir .../pdfs [--plain-names] [--frac 0.1 | --below -0.05]

--frac F    re-read the F least-confident fraction of this run (a per-job budget)
--below T   re-read every page with confidence < T (a fixed threshold, for streaming use)
Writes _reread.jsonl (one line per re-read page) and _reread_stats.json.

Since 2026-11-08, on top of the budget, pages are ALWAYS re-read when the ranking stage's output shows it failed
(see must_reread): the reader hit its output-token cap, its text is mostly repetition, or (born-digital PDFs) much
of it is not in the page's own text layer. A page whose previous reading was truncated or very long (dense), or whose
re-read is truncated, is read in tiles (docengine/tiles.py) at higher resolution. --no-must / --tile never restore the old behaviour.
"""

import argparse
import asyncio
import json
import os
import time

import httpx

import re

from docengine import textlayer
from docengine.layout import DROP_LABELS
from docengine.pipeline import READERS, RENDER_LONGEST, Recognizer, blocks_of, grounding_to_md, layout_size, render
from docengine.tiles import TILE_DPI, read_tiled


def repetition_share(text: str, n: int = 8) -> float:
    """Share of repeated word 8-grams, ignoring tables (which repeat legitimately). Degenerate reader output (loops,
    an invented list going on and on) scores high; real prose scores near 0."""
    text = re.sub(r"<table\b.*?</table>", " ", text, flags=re.S | re.I)
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("|"))
    w = re.findall(r"\w+", text.lower())
    if len(w) < 300:
        return 0.0
    grams = [tuple(w[i:i + n]) for i in range(len(w) - n + 1)]
    return 1 - len(set(grams)) / len(grams)


# A reading this long means a very dense page (normal pages: 4 of 1,403 olmOCR-Bench pages, 1 of 200 random web
# pages; stress pages at <= 5 pt: most). Such pages are re-read in tiles even when the reading finished.
DENSE_TOKENS = 7000


def must_reread(info: dict, md: str, pdf_path: str) -> list:
    """Reasons a page needs re-reading whatever the budget: the previous reading failed visibly."""
    why = []
    if info.get("finish") not in (None, "stop"):
        why.append("truncated")
    elif (info.get("n_tok") or 0) >= DENSE_TOKENS:
        why.append("dense")
    raw = info.get("raw", "")
    b = blocks_of("infinity" if raw.lstrip().startswith(("```json", "[{")) else "lighton", raw)
    if repetition_share("\n".join(t for _, _, t in b) if b else raw) > 0.5:
        why.append("repetitive")
    if pdf_path.lower().endswith(".pdf") and md.strip():
        layer = textlayer.extract(pdf_path)
        if layer["usable"] and textlayer.coverage(md, layer["text"])["precision"] < 0.6:
            why.append("not in text layer")
    return why


def default_size(path: str):
    """Pixel size of the default render (what the layout model saw), without rendering."""
    if path.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        w, h = pdf[0].get_size()
        pdf.close()
        s = RENDER_LONGEST / max(w, h)
        return w * s, h * s
    from PIL import Image
    w, h = Image.open(path).size
    s = min(1.0, RENDER_LONGEST / max(w, h))
    return w * s, h * s


def conf(info: dict) -> float:
    if info.get("finish") != "stop" or info.get("mean_lp") is None:
        return -1e9
    return info["mean_lp"]


def md_path(run_dir: str, rel: str, plain: bool) -> str:
    return os.path.join(run_dir, os.path.splitext(rel)[0] + ("" if plain else "_pg1_repeat1") + ".md")


async def run(args):
    pages = {d["page"]: d for d in map(json.loads, open(os.path.join(args.run_dir, "_pages.jsonl")))}
    # Ranking source: stage-1 confidence by default, or an earlier re-read stage's log (its reader's confidence,
    # covering only the pages that stage re-read). --frac is always a fraction of ALL pages in the run.
    ranked = pages if not args.rank_by else {
        d["page"]: d for d in map(json.loads, open(os.path.join(args.run_dir, args.rank_by)))}
    margins, regions = {}, {}
    lay = os.path.join(args.run_dir, "_layout.jsonl")
    for line in (open(lay) if os.path.exists(lay) else []):
        d = json.loads(line)
        regions[d["pdf"]] = d["regions"]
        margins[d["pdf"]] = [] if args.keep_margins else [r[3] for r in d["regions"] if r[1] in DROP_LABELS]
    order = sorted(ranked, key=lambda p: conf(ranked[p]))
    if args.below is not None:
        chosen = [p for p in order if conf(ranked[p]) < args.below]
    else:
        chosen = order[: int(round(args.frac * len(pages)))]
    cut = conf(ranked[chosen[-1]]) if chosen else None
    must = {}
    if args.must:  # pages whose current reading visibly failed are re-read whatever the budget
        for rel in ranked:
            p = md_path(args.run_dir, rel, args.plain_names)
            md = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
            why = must_reread(ranked[rel], md, os.path.join(args.pdf_dir, rel))
            if why:
                must[rel] = why
    budget = set(chosen)
    chosen = chosen + [p for p in must if p not in budget]

    stats = {"pages": len(pages), "reread": len(chosen), "budget": len(budget), "must": len(must),
             "must_outside_budget": len(set(must) - budget), "tiled": 0, "threshold": cut, "requests": 0,
             "retries": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "kept_stage1_empty": 0}
    rec = Recognizer(args.endpoint, args.model, stats, args.reader, keep_margins=args.keep_margins)
    if args.tile == "auto":  # one retry: a page that still loops or overflows is read in tiles instead (cheaper than
        rec.cfg = dict(rec.cfg, temps=rec.cfg["temps"][:2])  # more full-length attempts, which set the wall time)
    # Tiles are crops: a reader may call a crop's first line a "header", so margin labels are not dropped there;
    # page margins are already left out of the tiles by their layout regions.
    rec_tile = Recognizer(args.endpoint, args.model, stats, args.reader, keep_margins=True)
    rec_tile.cfg = dict(rec_tile.cfg, temps=rec_tile.cfg["temps"][:2])  # one retry per tile: a looping tile is junk
    cfg = READERS[args.reader]
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.time()
    suffix = f"_{args.tag}" if args.tag else ""
    log = open(os.path.join(args.run_dir, f"_reread{suffix}.jsonl"), "w", encoding="utf-8")

    async with httpx.AsyncClient(timeout=900) as client:

        async def tiled(rel, path):
            img = await asyncio.to_thread(render, path, TILE_DPI, 8192 * 8192)
            stats["tiled"] += 1
            return await read_tiled(rec_tile, client, img, default_size(path), regions.get(rel), sem,
                                    keep_margins=args.keep_margins)

        async def one(rel):
            path = os.path.join(args.pdf_dir, rel)
            prev = ranked[rel]
            prev_too_long = prev.get("finish") not in (None, "stop") or (prev.get("n_tok") or 0) >= DENSE_TOKENS
            if args.tile == "always" or (args.tile == "auto" and prev_too_long):
                md, info = await tiled(rel, path)
            else:
                img = await asyncio.to_thread(render, path, cfg.get("dpi"), cfg.get("max_pixels"))
                info = {}
                async with sem:
                    await rec(client, img, info=info)
                # Stage-1 layout boxes are in pixels of the default render (longest edge RENDER_LONGEST, images
                # never upscaled); block boxes are normalised 0-1000, so only the default render's size matters.
                size = layout_size(path, img, cfg)
                md = grounding_to_md(info.get("raw", ""), margins=margins.get(rel, ()), size=size,
                                     reader=args.reader, keep_margins=args.keep_margins)
                if args.tile == "auto" and (info.get("finish") != "stop" or repetition_share(md) > 0.5):
                    md, info = await tiled(rel, path)  # whole page did not fit: read it in pieces
            info["must"] = must.get(rel, [])
            if not md.strip():  # LightOn produced nothing usable: keep the stage-1 page
                stats["kept_stage1_empty"] += 1
            else:
                with open(md_path(args.run_dir, rel, args.plain_names), "w", encoding="utf-8") as f:
                    f.write(md)
            log.write(json.dumps({"page": rel, "rank_conf": conf(ranked[rel]), **info}, ensure_ascii=False) + "\n")

        await asyncio.gather(*(one(p) for p in chosen))
    log.close()
    stats["reread_seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(args.run_dir, f"_reread{suffix}_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--plain-names", action="store_true")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--frac", type=float, default=0.1)
    g.add_argument("--below", type=float, default=None)
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="lighton")
    ap.add_argument("--reader", default="lighton", choices=["lighton", "infinity"])
    ap.add_argument("--rank-by", default=None, help="rank by this jsonl in --run-dir (e.g. _reread_lt4.jsonl)")
    ap.add_argument("--tag", default="", help="name of this stage: writes _reread_<tag>.jsonl / _stats.json")
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--drop-margins", dest="keep_margins", action="store_false",
                    help="drop page headers/footers/page numbers/side notes (the olmOCR-Bench convention; "
                         "default since 2026-11-09: keep them)")
    ap.add_argument("--keep-margins", dest="keep_margins", action="store_true", help=argparse.SUPPRESS)  # old flag
    ap.set_defaults(keep_margins=True)
    ap.add_argument("--no-must", dest="must", action="store_false",
                    help="re-read only the budgeted pages (old behaviour), not also the visibly failed ones")
    ap.add_argument("--tile", choices=["auto", "never", "always"], default="auto",
                    help="auto: read in tiles when the previous or this reading was truncated/repetitive")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
