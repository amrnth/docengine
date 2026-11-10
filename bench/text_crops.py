"""Crops for eye-checking failed text tests on a category: block of our closest reading, test vs ours.
  text_crops.py run category seed n"""
import json, os, random, sys
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from rapidfuzz import fuzz
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from docengine.pipeline import blocks_of
PDFS = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")
def load(run, name):
    p = os.path.join(ROOT, "results", run, name)
    return {d["page"]: d for d in map(json.loads, open(p))} if os.path.exists(p) else {}
run, cat, seed, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
stages = [("infinity", load(run, "_reread_pro.jsonl")), ("lighton", load(run, "_reread_lt4.jsonl")), ("lighton", load(run, "_pages.jsonl"))]
drop = {json.loads(l)["id"] for l in open(os.path.join(ROOT, "failures/review/dropped_text.jsonl"))}
rows = [json.loads(l) for l in open(os.path.join(ROOT, "results", run, "_failures.jsonl"))]
rows = [r for r in rows if r["category"] == cat and r["type"] in ("present", "order") and r["id"] not in drop]
random.Random(seed).shuffle(rows)
tiles = []
for k, r in enumerate(rows[:n]):
    want = r.get("text") or r.get("before")
    md = open(os.path.join(ROOT, "results", run, r["pdf"][:-4] + "_pg1_repeat1.md"), encoding="utf-8").read()
    a = fuzz.partial_ratio_alignment(want.lower(), md.lower()); ours = md[a.dest_start:a.dest_end].replace("\n", " ")
    reader, d = next(((rd, s[r["pdf"]]) for rd, s in stages if r["pdf"] in s and s[r["pdf"]].get("raw")), (None, None))
    bl = blocks_of(reader, d["raw"]) if d else []
    b = max(bl, key=lambda b: fuzz.partial_ratio(want.lower(), b[2].lower()))[1] if bl else [0, 0, 1000, 1000]
    pdf = pdfium.PdfDocument(os.path.join(PDFS, r["pdf"])); img = pdf[0].render(scale=150 / 72).to_pil().convert("RGB"); pdf.close()
    W, H = img.size
    c = img.crop((max(0, b[0]*W/1000-20), max(0, b[1]*H/1000-15), min(W, b[2]*W/1000+20), min(H, b[3]*H/1000+15)))
    if c.width > 1100: c = c.resize((1100, int(c.height*1100/c.width)))
    c = c.crop((0, 0, c.width, min(c.height, 380)))
    ImageDraw.Draw(c).rectangle([0, 0, 44, 26], fill=(255, 255, 0)); ImageDraw.Draw(c).text((4, 2), str(k), fill=(0, 0, 0), font_size=22)
    tiles.append(c)
    print(f"[{k}] {r['pdf']} {r['type']}\n   TEST: {want[:200]!r}\n   OURS: {ours[:200]!r}")
sheet = Image.new("RGB", (1100, sum(t.height + 8 for t in tiles)), "white"); y = 0
for t in tiles: sheet.paste(t, (0, y)); y += t.height + 8
sheet.save(os.path.join(ROOT, "failures/review", f"text_sheet_{cat}_{seed}.png"))
