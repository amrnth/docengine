"""bench/gen_export.py JSONL -> DP-Bench prediction JSON (upstage/dp-bench format), scored by their evaluate.py in Docker.

  python bench/gen_dpbench.py results/modal_c3b_gen/_export_system.jsonl results/dpbench/docengine_c3b.json
  docker run --rm -v $PWD/data/dpbench:/dp:ro -v $PWD/results/dpbench:/out docengine-dpbench \
      --ref-path dataset/reference.json --pred-path /out/docengine_c3b.json

Elements = the blocks the system kept (its markdown, block by block, in reading order); tables carry their HTML in
content.html. Pages with no blocks (OvisOCR2 pages in v2) become one paragraph element holding the page markdown.
Coordinates: DP-Bench ground truth is in pixels at 3x PDF points (216 DPI; the largest reference x/width ratio is
2.94), used only by their filter that drops predicted text inside ground-truth figure/table/chart regions.
"""
import json
import re
import sys

SCALE = 3.0
CAT = {"table": "table", "image": "figure", "figure": "figure", "chart": "chart", "title": "heading1",
       "formula": "equation", "caption": "caption", "figure_title": "caption", "footnote": "footnote",
       "header": "header", "footer": "footer", "page_number": "footer", "list": "list"}
TAG = re.compile(r"<[^>]+>")


def element(i, cat, box, W, H, text):
    x0, y0, x1, y1 = (box[0] * W * SCALE / 1000, box[1] * H * SCALE / 1000, box[2] * W * SCALE / 1000,
                      box[3] * H * SCALE / 1000)
    plain = TAG.sub(" ", text) if cat == "table" else text
    return {"coordinates": [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}],
            "category": cat, "id": i, "page": 1,
            "content": {"text": plain, "html": text if cat == "table" else "", "markdown": text}}


def main(src, dst, kept_only=True):
    out = {}
    for line in open(src, encoding="utf-8"):
        d = json.loads(line)
        if not d["rel"].startswith("dpbench/"):
            continue
        key = d["rel"].split("/", 1)[1]
        W, H = d["w"], d["h"]
        blocks = [b for b in d["blocks"] if b["text"] and (b["kept"] or not kept_only)]
        if blocks:
            els = [element(i, CAT.get(b["label"].lower().rstrip("+"), "paragraph"), b["box"], W, H, b["text"])
                   for i, b in enumerate(blocks)]
        else:  # no boxes: the whole page as one element (tables inside still found by their <table> HTML)
            md = d["md"]
            els = [element(0, "paragraph", [0, 0, 1000, 1000], W, H, re.sub(r"<table.*?</table>", "", md, flags=re.S))]
            for j, t in enumerate(re.findall(r"<table.*?</table>", md, re.S)):
                els.append(element(j + 1, "table", [0, 0, 1000, 1000], W, H, t))
        out[key] = {"elements": els}
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False)
    print(len(out), "pages ->", dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], kept_only="--all-blocks" not in sys.argv)
