"""Use a born-digital PDF's own text layer as a reference for the vision readers' output.

The readers see pixels. A born-digital PDF also carries the exact characters it was typeset from. That text has no
structure (no reading order across columns, no tables or maths markup) and can be junk (fonts with custom encodings,
invisible OCR layers of scans of unknown quality), so it is used as a *reference*, not as the output:

  extract(path)       the page's text layer + whether it is usable (visible text, not junk)
  coverage(md, layer) word recall / precision of our markdown against the layer (routing signal: dropped or
                      invented text)
  correct(md, layer)  word-level spelling correction: where our word and the layer's word are aligned 1:1 between
                      matching neighbours and are near-identical (a misread letter, a lost accent, a mangled rare
                      word, a wrong digit), take the layer's spelling. Markdown/LaTeX/HTML markup, maths and
                      anything not aligned 1:1 is left alone, so structure and reading order stay the reader's.

CLI (offline, no GPU): rewrite a finished run's markdown into a new directory
  python -m docengine.textlayer --run-dir results/run --pdf-dir data/.../pdfs --out-dir results/run_tl [--plain-names]
Writes <out>/_textlayer.jsonl (per page: layer mode, usable, coverage before/after, changes) and _textlayer_stats.json.
"""
import argparse
import collections
import json
import os
import re
import shutil
import threading
import unicodedata

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from rapidfuzz.distance import Levenshtein

_LOCK = threading.Lock()
WORD = re.compile(r"[^\W_]+(?:['’.,\-][^\W_]+)*", re.U)
# Spans of our markdown that must not be touched: maths, HTML tags (cell text between tags is fair game),
# code, image/link targets, URLs and e-mail addresses.
PROTECT = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|\$[^$\n]+\$|```.*?```|`[^`\n]+`|<[^>\n]*>|\]\([^)]*\)|"
    r"https?://\S+|www\.\S+|\S+@\S+\.\w+", re.S)


def _layer_mode(page) -> str:
    """'visible', 'invisible' (an OCR layer over a scan: text drawn with render mode 3, or text lying under a later
    drawn image) or 'none'."""
    texts, images = [], []
    inv = 0
    for o in page.get_objects(max_depth=4):
        if o.type == pdfium_c.FPDF_PAGEOBJ_TEXT:
            if pdfium_c.FPDFTextObj_GetTextRenderMode(o.raw) == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
                inv += 1
            else:
                texts.append((len(images), o.get_bounds()))
        elif o.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            images.append(o.get_bounds())

    def covered(i, box):
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in images[i:])  # an image drawn after it
    hidden = sum(covered(i, b) for i, b in texts)
    if texts and hidden > 0.5 * len(texts):
        return "invisible"
    return "visible" if texts else ("invisible" if inv else "none")


LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


def normalise(text: str) -> str:
    # NFC plus ligatures only: NFKC would also rewrite real symbols (µ -> μ, ™ -> TM, ² -> 2).
    text = text.replace("￾", "").replace("\x02", "").replace("­", "").replace("\r", "\n")
    text = unicodedata.normalize("NFC", "".join(LIGATURES.get(c, c) for c in text))
    return re.sub(r"(\w)-\n\s*(?=[a-zà-ÿ])", r"\1", text)  # re-join words hyphenated at a line end


def junk_score(text: str) -> float:
    """Share of non-space characters that are neither letters, digits nor ordinary punctuation. Fonts with a custom
    encoding come out as runs of symbols like '¤·²Æª' and score high; real text in any script scores low."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 1.0
    bad = sum(1 for c in chars if not (c.isalnum() or unicodedata.category(c)[0] in "PS" and c in
                                       ".,;:!?'\"()[]{}-–—/\\%&*+=<>#@$€£¥°§|~^_…‘’“”«»•·")
              or unicodedata.category(c) in ("Co", "Cn", "Cc") or c == "�")
    return bad / len(chars)


def exotic_latin_share(text: str) -> float:
    """Share of letters in Latin Extended-B / IPA (U+0180-U+02AF). Real text in any language rarely has many; a font
    whose glyphs were mapped to arbitrary codes ('ƾƤŤƯŚĪǀƴƯ' for Persian) is mostly made of them."""
    letters = [c for c in text if c.isalpha()]
    return sum(0x180 <= ord(c) <= 0x2AF for c in letters) / max(1, len(letters))


def extract(path: str) -> dict:
    """{'mode', 'text', 'words', 'usable', 'why'} for page 1 of a PDF (images: mode 'none')."""
    if not path.lower().endswith(".pdf"):
        return {"mode": "none", "text": "", "words": 0, "usable": False, "why": "not a pdf"}
    with _LOCK:
        pdf = pdfium.PdfDocument(path)
        page = pdf[0]
        mode = _layer_mode(page)
        raw = page.get_textpage().get_text_range() if mode != "none" else ""
        pdf.close()
    text = normalise(raw)
    n = len(WORD.findall(text))
    js = max(junk_score(text), exotic_latin_share(text))
    why = ("no text layer" if mode == "none" else "invisible OCR layer" if mode == "invisible" else
           "too little text" if n < 20 else f"junk characters ({js:.0%})" if js > 0.12 else "")
    return {"mode": mode, "text": text, "words": n, "junk": round(js, 3), "usable": not why, "why": why}


def _tokens(s: str):
    return [w.lower() for w in WORD.findall(s)]


def coverage(md: str, layer_text: str) -> dict:
    """Word recall (layer words we output) and precision (our words found in the layer), order-free."""
    a = collections.Counter(_tokens(PROTECT.sub(" ", md)))
    b = collections.Counter(_tokens(layer_text))
    inter = sum((a & b).values())
    return {"recall": round(inter / max(1, sum(b.values())), 4), "precision": round(inter / max(1, sum(a.values())), 4)}


TABLES = re.compile(r"<table\b.*?</table>|(?:^[ \t]*\|.*\|[ \t]*$\n?)+", re.S | re.M | re.I)


def _md_tokens(md: str):
    """(start, end, word, in_table) for every word of the markdown outside protected spans."""
    tables = [(m.start(), m.end()) for m in TABLES.finditer(md)]
    out, pos = [], 0
    for m in list(PROTECT.finditer(md)) + [None]:
        stop = m.start() if m else len(md)
        for w in WORD.finditer(md, pos, stop):
            out.append((w.start(), w.end(), w.group(), any(a <= w.start() < b for a, b in tables)))
        if m:
            pos = m.end()
    return out


def _alnum(s: str) -> str:
    # NFKC here (comparison only): ³ == 3, ₃ == 3, ４ == 4, so formatting-only differences are not "fixed"
    return "".join(c for c in unicodedata.normalize("NFKC", s).casefold() if c.isalnum())


def _case_class(w: str) -> str:
    letters = [c for c in w if c.isalpha()]
    if not letters:
        return "none"
    if all(c.isupper() for c in letters):
        return "upper"
    if all(c.islower() for c in letters):
        return "lower"
    if letters[0].isupper() and all(c.islower() for c in letters[1:]):
        return "title"
    return "mixed"


def _fixable(ours: str, theirs: str, in_table: bool = False) -> bool:
    """Take the layer's spelling only for a near-identical word, and never when the difference looks like a known
    text-layer defect rather than a misread: missing spaces between words ('revealedthat'), spacing accents or
    re-encoded letters ('Geocieˆncias', 'koƒczyny'), hyphen/punctuation/case-only differences, or short words."""
    o, t = ours.casefold(), theirs.casefold()
    if _alnum(ours) == _alnum(theirs):  # case, hyphens, apostrophes, punctuation only
        return False
    num_o, num_t = any(c.isdigit() for c in ours), any(c.isdigit() for c in theirs)
    if num_o != num_t:
        return False
    if num_t:  # numbers: layer order in tables is unreliable, so never there; elsewhere one wrong digit at most
        if in_table or len(ours) != len(theirs) or sum(x != y for x, y in zip(ours, theirs)) > 1:
            return False
    if (len(ours) < 4 or len(theirs) < 4) and not num_t:  # short words: easy to align with the wrong neighbour
        return False
    if t.startswith(o) or t.endswith(o) or o.startswith(t) or o.endswith(t):
        return False  # words glued/split differently at an edge ('contractin', 'spond', '10th')
    if (o in t and len(t) >= len(o) + 2) or (t in o and len(o) >= len(t) + 2):
        return False
    eo = Levenshtein.editops(o, t)
    if eo and all(e.tag == "delete" for e in eo) and len(eo) <= 3 and all(o[e.src_pos] in "filt" for e in eo):
        return False  # the layer lost (part of) a ligature glyph ('filling' -> 'lling', 'trafic' -> 'traic')
    if _case_class(ours) != _case_class(theirs):  # 'UNIVERSITY' -> 'UNIVERSIHj' is OCR junk, not a fix
        return False
    if any(unicodedata.category(c) in ("Sk", "Lm", "Mn", "Co", "So") or c in "ƒ�" for c in theirs):
        return False
    accents_o = {c for c in ours if ord(c) > 127 and c.isalpha()}
    if accents_o - set(theirs):  # never drop or swap a non-ASCII letter the reader saw ('ń' -> 'ƒ')
        return False
    a = unicodedata.normalize("NFKD", ours.lower())
    b = unicodedata.normalize("NFKD", theirs.lower())
    return Levenshtein.normalized_similarity(a, b) >= (0.5 if num_t else 0.6)


def correct(md: str, layer_text: str, context: int = 1):
    """Return (corrected markdown, list of (ours, layer) substitutions). Only 1:1-aligned near-identical words whose
    neighbours align exactly on both sides (or >= 3 words on one side) are replaced."""
    toks = _md_tokens(md)
    if not toks:
        return md, []
    ours = [t[2] for t in toks]
    theirs = WORD.findall(layer_text)
    a, b = [w.lower() for w in ours], [w.lower() for w in theirs]
    ops = Levenshtein.opcodes(a, b)
    subs = {}
    for k, op in enumerate(ops):
        if op.tag != "replace" or (op.src_end - op.src_start) != (op.dest_end - op.dest_start):
            continue
        prev_n = ops[k - 1].src_end - ops[k - 1].src_start if k > 0 and ops[k - 1].tag == "equal" else 0
        next_n = ops[k + 1].src_end - ops[k + 1].src_start if k + 1 < len(ops) and ops[k + 1].tag == "equal" else 0
        if not ((prev_n >= context and next_n >= context) or max(prev_n, next_n) >= 3):
            continue  # anchored on both sides, or by a run of >= 3 matching words on one side
        for i, j in zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end)):
            if _fixable(ours[i], theirs[j], toks[i][3]):
                subs[i] = theirs[j]
    if not subs:
        return md, []
    out, last, changes = [], 0, []
    for i, (s, e, w, _) in enumerate(toks):
        if i in subs:
            out.append(md[last:s])
            out.append(subs[i])
            last = e
            changes.append((w, subs[i]))
    out.append(md[last:])
    return "".join(out), changes


def layer_markdown(text: str) -> str:
    """The text layer as plain paragraphs: lines joined, a paragraph ending where a line ends a sentence."""
    paras, cur = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        cur.append(line)
        if line.endswith((".", "!", "?", ":", "。", "！", "？")):
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


def check(md: str, path: str, min_agree: float = 0.5):
    """Everything the pipeline needs for one page: (layer info, coverage, corrected md, changes). Correction is only
    applied when the layer is usable AND agrees with our reading on at least `min_agree` of its words, so a layer
    that is valid text but not what is on the page (e.g. hidden text) is never trusted.

    Fallback: when the page's fonts cannot be drawn (the readers see empty boxes) our reading has almost no words
    while the layer is clean text. If our markdown holds fewer than a fifth of the layer's words, the layer itself
    becomes the page's text (changes = [('<page>', '<text layer>')])."""
    info = extract(path)
    if not info["usable"]:
        return info, None, md, []
    ours = sum(c.isalnum() for c in re.sub(r"</?[a-zA-Z][^<>]*>|\\[a-zA-Z]+", " ", md))  # HTML tags, LaTeX commands
    theirs = sum(c.isalnum() for c in info["text"])
    if info["words"] >= 50 and ours < 0.2 * theirs:
        info["why"] = "reading nearly empty: text layer used as output"
        return info, coverage(md, info["text"]), layer_markdown(info["text"]), [("<page>", "<text layer>")]
    cov = coverage(md, info["text"])
    if cov["recall"] < min_agree and cov["precision"] < min_agree:
        info["why"] = "disagrees with the page reading"
        return info, cov, md, []
    new, changes = correct(md, info["text"])
    return info, cov, new, changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--plain-names", action="store_true")
    args = ap.parse_args()
    suffix = "" if args.plain_names else "_pg1_repeat1"
    stats = collections.Counter()
    os.makedirs(args.out_dir, exist_ok=True)
    log = open(os.path.join(args.out_dir, "_textlayer.jsonl"), "w", encoding="utf-8")
    for root, _, files in os.walk(args.pdf_dir):
        for f in sorted(files):
            if not f.lower().endswith(".pdf"):
                continue
            rel = os.path.relpath(os.path.join(root, f), args.pdf_dir)
            src = os.path.join(args.run_dir, os.path.splitext(rel)[0] + suffix + ".md")
            if not os.path.exists(src):
                continue
            md = open(src, encoding="utf-8").read()
            info, cov, new, changes = check(md, os.path.join(args.pdf_dir, rel))
            dst = os.path.join(args.out_dir, os.path.splitext(rel)[0] + suffix + ".md")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(new)
            stats["pages"] += 1
            stats[f"layer_{info['mode']}"] += 1
            stats["usable" if info["usable"] and cov and not info["why"] else "not_used"] += 1
            stats["pages_changed"] += bool(changes)
            stats["words_changed"] += len(changes)
            log.write(json.dumps({"page": rel, "mode": info["mode"], "why": info["why"], "layer_words": info["words"],
                                  "coverage": cov, "changes": changes[:50], "n_changes": len(changes)},
                                 ensure_ascii=False) + "\n")
    log.close()
    json.dump(dict(stats), open(os.path.join(args.out_dir, "_textlayer_stats.json"), "w"), indent=2)
    print(json.dumps(dict(stats), indent=2))


if __name__ == "__main__":
    main()
