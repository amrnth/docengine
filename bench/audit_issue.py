"""Write the upstream report for the audit: reports/audit/upstream_issue.md (self-contained, for a GitHub issue).

  .venv/bin/python bench/audit_issue.py

For each wrong text test it shows only the part of the expected string that differs from the page, with the
differences in bold, and the page's string in its original case (from the PDF's stored text).
"""
import difflib
import json
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_tests import OUT, _infix, layer_variants, page_info, strip_accents  # noqa: E402

from olmocr.bench.tests import normalize_text  # noqa: E402

REV = "54a96a6fb6a2bd3b297e59869491db4d3625b711"


def page_string(pdf, want):
    """Nearest stretch of the stored text to `want` (original case), widened to whole words, and the 2 words before it."""
    best = None
    for v in layer_variants(page_info(pdf, 1)[0]):
        d, end = _infix(want, v)
        _, rlen = _infix(want[::-1], v[:end][::-1])
        if best is None or d < best[0]:
            best = (d, v, end - rlen, end)
    _, v, st, en = best
    while st > 0 and not v[st - 1].isspace():
        st -= 1
    while en < len(v) and not v[en].isspace():
        en += 1
    return v[st:en].split(), v[:st].split()[-2:]


def key(tok):
    return strip_accents(tok)


def mark(want, page, before, ctx=4):
    """Both strings as words, cut to the part where they differ (+ctx words), with the differing words in bold."""
    a = want.split()
    b = [t for t in page if key(t)]  # drop tokens that are only a loose accent mark of the stored text
    ops = difflib.SequenceMatcher(None, [key(t) for t in a], [key(t) for t in b], autojunk=False).get_opcodes()
    if ops[0][0] != "equal" and ops[0][4] - ops[0][3] < ops[0][2] - ops[0][1]:  # the test starts with extra words: show what the page has before
        b = before + b
        ops = difflib.SequenceMatcher(None, [key(t) for t in a], [key(t) for t in b], autojunk=False).get_opcodes()
    diff = [o for o in ops if o[0] != "equal"]
    if not diff:
        return want, " ".join(b)

    def build(toks, lo, hi, spans):
        lo, hi = max(0, lo - ctx), min(len(toks), hi + ctx)
        bold = set(i for x, y in spans for i in range(x, y))
        out, i = [], lo
        while i < hi:
            if i in bold:
                j = i
                while j < hi and j in bold:
                    j += 1
                out.append("**" + " ".join(toks[i:j]) + "**")
                i = j
            else:
                out.append(toks[i])
                i += 1
        return ("… " if lo > 0 else "") + " ".join(out) + (" …" if hi < len(toks) else "")
    return (build(a, diff[0][1], diff[-1][2], [(o[1], o[2]) for o in diff]),
            build(b, diff[0][3], diff[-1][4], [(o[3], o[4]) for o in diff]))


def esc(s):
    return s.replace("|", "\\|").replace("\n", " ")


def main():
    review = json.load(open(os.path.join(OUT, "review.json")))
    S = json.load(open(os.path.join(OUT, "summary.json")))
    cand = [json.loads(l) for l in open(os.path.join(OUT, "wrong_tests.jsonl"))]
    rows = []
    for r in cand:
        if not r["confirmed"] or r["id"] in review["rejected"]:
            continue
        for p in r["parts"]:
            if p.get("confirmed"):
                want = normalize_text(unicodedata.normalize("NFC", p["want"]))
                a, b = mark(want, *page_string(r["pdf"], want))
                rows.append("| `%s` | %s (`%s`) | %s | %s |" % (r["id"], r["type"], p["key"], esc(a), esc(b)))
    L = [f"""Thank you for olmOCR-bench. I use it a lot, and I found some tests that I think need a second look.

**Summary.** In dataset revision `{REV[:7]}` there are 38 tests, all marked `checked: verified`, that a faithful transcription of the page cannot pass:

- **32 `order` / `present` tests** expect a string that is not what the page shows. Examples: the test has "sternum" where the page has "scrotum", "line 2 of the Schedule D" for "line 37a of Schedule D", "Barkschat R (2021)" for "Blankertz B (2001)".
- **6 `absent` tests** forbid a string that is also part of the body text of the same page.

Together they are worth {S['points_locked_by_wrong_tests']} points of the overall score (28 of 884 in `multi_column`, 4 of 442 in `long_tiny_text`, 6 of 760 in `headers_footers`).

**How I found them**

1. For every `present` / `order` test on a page that has embedded text, I applied the test's own rule (same `normalize_text`, same `max_diffs`) to the text stored in the PDF. To allow for artefacts of the stored text, a match also counts with line-break hyphens joined, accents removed, case ignored, or all spaces removed. 1,100 tests could be checked; 120 had no match.
2. I kept a test only if the stored text has a different string in that place, and at least 3 of 4 unrelated model families (LightOnOCR-3, Infinity-Parser2, olmOCR-2, OvisOCR2) output that string and not the test's string. This removes the cases where the stored text itself is wrong (OCR layers, lost ligatures). 37 tests were left.
3. I looked at a crop of the page for each one and dropped 5 (one test was right, four were layout or convention questions). For one of the 32 that are left (`019a8841dddeb304774ba62a9f5d8dccb43d_page_1.pdf_order_87cd96c5`) my crop missed the sentence, so that row rests on the embedded text and the four models only.

None of the 14 runs I have (the four families above and cascades of them) passes any of the 32 tests.

This method cannot check scanned pages, math or tables, so I have nothing to say about those. I may also be wrong on some rows; please tell me if so.

### A. Expected string differs from the page (32 tests)

Only the part that differs is shown, with the differing words in bold. "Page shows" is the PDF's embedded text. Differences that are only an accent are not marked.

| Test id | Type (field) | Test expects | Page shows |
|---|---|---|---|"""]
    L += rows
    L += ["", "### B. `absent` tests whose string is also body text (6 tests)", "", "| Test id | Problem |", "|---|---|"]
    L += ["| `%s` | %s |" % (i, esc(why)) for i, why in review["headers_footers_wrong"].items()]
    L += ["", "**Suggested fix.** For A, replace the expected string with the page's string (or remove the test). For B, remove the test or limit it with `first_n` / `last_n` so that the body text is outside its range.",
          "", "I can send the corrected JSONL lines, or a pull request on the Hugging Face dataset, if that helps. I also have a page crop for every row."]
    open(os.path.join(OUT, "upstream_issue.md"), "w").write("\n".join(L) + "\n")
    print(len(rows), "rows")


if __name__ == "__main__":
    main()
