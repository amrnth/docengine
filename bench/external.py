"""Run a commercial document API (Datalab or Reducto) over one of our page sets, so its output can be scored with the
same scripts as ours.

  set -a && . ./.env && set +a          # DATALAB_API_KEY / REDUCTO_API_KEY; never printed
  .venv/bin/python bench/external.py datalab --set stress --mode accurate
  .venv/bin/python bench/external.py reducto --set rcc

Sets (all single-page PDFs):
  olmocr  data/olmOCR-bench/bench_data/pdfs/<cat>/*.pdf -> results/<key>/<cat>/<stem>_pg1_repeat1.md
  rcc     data/random_cc/pages/*.pdf                    -> results/<key>/<stem>.md
  stress  data/stress/pages/*.pdf                       -> results/<key>/<stem>.md

Default key: ext_<service>_<mode>_<set>. Re-running resumes (pages with an .md are skipped). Per-page time, cost and
errors go to _external.jsonl; totals to _timing.json.

Settings: Datalab /api/v1/convert, markdown, images not extracted (headers/footers dropped by default, like ours).
Reducto /parse with model r-1 (or r-1-mini), tables as markdown/html ("dynamic"), one chunk. Neither service is
told anything about the benchmark.
"""
import argparse
import asyncio
import glob
import json
import os
import random
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = "https://www.datalab.to/api/v1/convert"
RD = "https://platform.reducto.ai"


def inputs(which):
    if which == "olmocr":
        base = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")
        for p in sorted(glob.glob(os.path.join(base, "*", "*.pdf"))):
            cat = os.path.basename(os.path.dirname(p))
            yield p, os.path.join(cat, os.path.basename(p)[:-4] + "_pg1_repeat1.md")
    else:
        base = {"rcc": ("random_cc", "pages"), "stress": ("stress", "pages")}[which]
        for p in sorted(glob.glob(os.path.join(ROOT, "data", *base, "*.pdf"))):
            yield p, os.path.basename(p)[:-4] + ".md"


async def with_retry(fn, tries=12):
    for k in range(tries):
        try:
            return await fn()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code not in (408, 429, 500, 502, 503, 504) or k == tries - 1:
                raise
            ra = e.response.headers.get("retry-after")
            await asyncio.sleep(float(ra) if ra and ra.isdigit() else (60 if code == 429 else min(60, 2 ** k * 3)) + 5 * random.random())
        except (httpx.TransportError, httpx.TimeoutException):
            if k == tries - 1:
                raise
            await asyncio.sleep(2 ** k + random.random())


async def datalab(client, path, mode):
    key = os.environ["DATALAB_API_KEY"]
    h = {"X-API-Key": key}

    async def submit():
        with open(path, "rb") as f:
            r = await client.post(DL, headers=h, files={"file": (os.path.basename(path), f, "application/pdf")},
                                  data={"output_format": "markdown", "mode": mode, "page_range": "0",
                                        "disable_image_extraction": "true", "skip_cache": "true"})
        r.raise_for_status()
        return r.json()

    j = await with_retry(submit)
    if not j.get("success", True) and not j.get("request_check_url"):
        raise RuntimeError(f"submit failed: {j.get('error')}")
    url, wait = j["request_check_url"], 0.5
    for _ in range(1200):
        await asyncio.sleep(wait)
        wait = min(3.0, wait * 1.5)

        async def poll():
            r = await client.get(url, headers=h)
            r.raise_for_status()
            return r.json()

        d = await with_retry(poll)
        if d.get("status") in ("complete", "failed"):
            if d.get("result_url"):
                r = await client.get(d["result_url"])
                r.raise_for_status()
                d = {**{k: v for k, v in d.items() if v is not None}, **r.json()}
            if not d.get("success"):
                raise RuntimeError(f"failed: {d.get('error')}")
            return d.get("markdown") or "", {"cost": d.get("cost_breakdown"), "quality": d.get("parse_quality_score"),
                                             "page_count": d.get("page_count")}
    raise TimeoutError("datalab poll timeout")


async def reducto(client, path, mode):
    h = {"Authorization": "Bearer " + os.environ["REDUCTO_API_KEY"]}

    async def upload():
        with open(path, "rb") as f:
            r = await client.post(RD + "/upload", headers=h, files={"file": (os.path.basename(path), f, "application/pdf")})
        r.raise_for_status()
        return r.json()["file_id"]

    fid = await with_retry(upload)
    body = {"input": fid, "formatting": {"table_output_format": "dynamic"},
            "retrieval": {"chunking": {"chunk_mode": "disabled"}},
            "settings": {"page_range": {"start": 1, "end": 1}, "model": mode}}

    async def parse():
        r = await client.post(RD + "/parse", headers=h, json=body, timeout=600)
        r.raise_for_status()
        return r.json()

    d = await with_retry(parse)
    res = d.get("result") or {}
    if res.get("type") == "url":
        r = await client.get(res["url"])
        r.raise_for_status()
        res = r.json()
        res = res.get("result", res) if isinstance(res, dict) and "chunks" not in res else res
    chunks = res.get("chunks", []) if isinstance(res, dict) else res
    md = "\n\n".join(c.get("content", "") for c in chunks)
    return md, {"usage": d.get("usage"), "duration": d.get("duration"), "job_id": d.get("job_id")}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("service", choices=["datalab", "reducto"])
    ap.add_argument("--set", required=True, choices=["olmocr", "rcc", "stress"])
    ap.add_argument("--mode", help="datalab: fast|balanced|accurate (default accurate); reducto: r-1|r-1-mini (default r-1)")
    ap.add_argument("--key")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    mode = args.mode or ("accurate" if args.service == "datalab" else "r-1")
    key = args.key or f"ext_{args.service}_{mode.replace('-', '')}_{args.set}"
    out = os.path.join(ROOT, "results", key)
    os.makedirs(out, exist_ok=True)
    todo = [(p, rel) for p, rel in inputs(args.set) if not os.path.exists(os.path.join(out, rel))]
    if args.limit:
        todo = todo[:args.limit]
    fn = datalab if args.service == "datalab" else reducto
    sem = asyncio.Semaphore(args.concurrency)
    log = open(os.path.join(out, "_external.jsonl"), "a")
    done = errs = 0
    t0 = time.time()

    async def one(client, p, rel):
        nonlocal done, errs
        async with sem:
            s = time.time()
            rec = {"page": rel, "pdf": os.path.relpath(p, ROOT)}
            try:
                md, info = await fn(client, p, mode)
                dst = os.path.join(out, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(md)
                rec.update(info)
            except Exception as e:  # noqa: BLE001 - record and continue; rerun resumes
                errs += 1
                rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            rec["seconds"] = round(time.time() - s, 2)
            log.write(json.dumps(rec) + "\n")
            log.flush()
            done += 1
            if done % 25 == 0 or done == len(todo):
                print(f"{done}/{len(todo)} done, {errs} errors, {time.time() - t0:.0f}s", flush=True)

    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=30)) as client:
        await asyncio.gather(*(one(client, p, rel) for p, rel in todo))
    t = {"service": args.service, "mode": mode, "set": args.set, "pages": len(todo), "errors": errs,
         "wall_seconds": round(time.time() - t0, 1)}
    json.dump(t, open(os.path.join(out, "_timing.json"), "w"), indent=2)
    print(json.dumps(t))


if __name__ == "__main__":
    asyncio.run(main())
