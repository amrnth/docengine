"""Inside the docengine-parsebench container: turn a bench/gen_export.py JSONL into ParseBench result files.

  docker run --rm -v $PWD:/w -w /w --entrypoint python docengine-parsebench bench/gen_parsebench.py \
      results/modal_c3b_gen/_export_system.jsonl results/parsebench/docengine_c3b

Markdown = the system's markdown, unchanged. Layout (the visual-grounding dimension) = every block of the reader that
produced the page, labelled with ParseBench's own label maps for that reader (lightonocr-3 / infinity_parser2
providers) and built with their layout-page builder; pages with no boxes (OvisOCR2) carry no layout.
Output: <out>/<group>/<stem>.result.json, group = chart | layout | table | text (ParseBench's test ids).
"""
import importlib
import json
import os
import sys
from datetime import datetime, timezone

from parse_bench.inference.providers.parse.qwen import _build_layout_page
from parse_bench.schemas.parse_output import PageIR, ParseOutput
from parse_bench.schemas.pipeline_io import InferenceRequest, InferenceResult

lo = importlib.import_module("parse_bench.inference.providers.parse.lightonocr-3")
# Copied from parse_bench/inference/providers/parse/infinity_parser2.py (importing it needs the infinity SDK deps).
INFINITY_CATEGORY_MAP = {
    "header": "Page-header", "title": "Section-header", "text": "Text", "figure": "Picture", "table": "Table",
    "formula": "Formula", "figure_caption": "Caption", "table_caption": "Caption", "formula_caption": "Caption",
    "figure_footnote": "Footnote", "table_footnote": "Footnote", "page_footnote": "Footnote", "footer": "Page-footer",
}

SECTIONS = {"lighton": lo._PAGE_SECTIONS,
            "infinity": {"page_header_markdown": {"header"}, "page_footer_markdown": {"footer", "page_footnote"},
                         "printed_page_number": set()}}


def category(reader, label):
    base = label.strip().lower().rstrip("+")
    if reader == "infinity":
        return INFINITY_CATEGORY_MAP.get(base, "Text")
    return lo.LABEL_MAP.get(base, "Text")


# ParseBench picks the layout adapter from the result's pipeline name. Our layout pages are built exactly as its
# lightonocr-3 provider builds them (0-1000 boxes -> [0,1] segments via _build_layout_page), so results carry that
# registered pipeline name, whose adapter (QwenLayoutAdapter) reads them back; an unknown name falls through to a
# LlamaParse-specific adapter that matches nothing. Only the layout adapter depends on the name.
PIPELINE_NAME = "lightonocr_3_vllm_parse"


def main(src, out_dir):
    name = PIPELINE_NAME
    now = datetime.now(timezone.utc)
    n = 0
    for line in open(src, encoding="utf-8"):
        d = json.loads(line)
        if not d["rel"].startswith("parsebench/"):
            continue
        group, fname = d["rel"].split("/")[1:3]
        stem = os.path.splitext(fname)[0]
        test_id = f"{group}/{stem}"
        md = d["md"]
        layout_pages = []
        if d["blocks"]:
            items = [{"bbox": b["box"], "category": category(d["reader"], b["label"]), "text": b["text"]}
                     for b in d["blocks"]]
            W, H = d["w"], d["h"]
            page = _build_layout_page(layout_items=items, page_number=1, img_width=int(round(W)),
                                      img_height=int(round(H)), page_markdown=md)
            for field, labels in SECTIONS[d["reader"]].items():
                texts = [b["text"] for b in d["blocks"] if b["label"].lower().rstrip("+") in labels and b["text"]]
                setattr(page, field, "\n\n".join(texts))
            layout_pages.append(page)
        output = ParseOutput(task_type="parse", example_id=test_id, pipeline_name=name,
                             pages=[PageIR(page_index=0, markdown=md)], layout_pages=layout_pages, markdown=md)
        req = InferenceRequest(example_id=test_id, source_file_path=f"docs/{group}/{fname}", product_type="parse")
        res = InferenceResult(request=req, pipeline_name=name, product_type="parse",
                              raw_output={"reader": d["reader"]}, output=output,
                              started_at=now, completed_at=now, latency_in_ms=0)
        path = os.path.join(out_dir, group, stem + ".result.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(res.model_dump_json(indent=1))
        n += 1
    print(n, "results ->", out_dir)


if __name__ == "__main__":
    main(*sys.argv[1:3])
