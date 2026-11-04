"""Person 3, Task 1: page text for all 105 contingency plans.

Writes plan_text/<State>/<District>.json, one record per page, plus
plan_text/index.csv summarising every plan.

    python p3/extract_text.py
"""
import csv
import hashlib
import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "DOCS" / "data" / "Main EL"
PLANS = DATA / "data" / "plans"
LINKS = DATA / "contingency_plan_links.csv"
OUT = ROOT / "plan_text"

# a page with fewer characters than this is flagged as possibly scanned
MIN_CHARS = 50


def clean(text):
    """Collapse runs of spaces and blank lines; keep one table cell per line."""
    lines = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def tables(page):
    """Tables on the page as Markdown rows rebuilt by PyMuPDF.

    Returns (tables, merges). In `tables` merged cells come out empty. merges[t] lists
    [row, col, source_row] for table t: that empty cell is covered by a vertically merged
    cell starting at source_row (row numbers count the Markdown rows of tables[t]), e.g. one
    'No change' spanning five crop rows. rules.filled_tables() applies it."""
    out, merges = [], []
    try:
        found = page.find_tables().tables
    except Exception:
        return out, merges
    for t in found:
        ext = t.extract()
        boxes = [r.cells for r in t.rows]
        rows, kept = [], {}
        for i, row in enumerate(ext):
            cells = [re.sub(r"\s+", " ", c or "").strip() for c in row]
            if any(cells):
                kept[i] = len(rows)
                rows.append("| " + " | ".join(cells) + " |")
        if not rows:
            continue
        spans = []
        for i, row in enumerate(ext):
            top = t.rows[i].bbox[1]
            for c, val in enumerate(row):
                if val is not None or i not in kept:
                    continue
                for k in range(i - 1, -1, -1):  # nearest real cell above in this column
                    box = boxes[k][c] if c < len(boxes[k]) else None
                    if box is not None:
                        if box[3] > top + 1 and k in kept and ext[k][c]:  # reaches into this row
                            spans.append([kept[i], c, kept[k]])
                        break
        out.append("\n".join(rows))
        merges.append(spans)
    return out, merges


def load_links():
    with open(LINKS, encoding="utf-8") as f:
        return {(r["state"], r["district"]): r for r in csv.DictReader(f)}


def extract(pdf, meta):
    doc = pymupdf.open(pdf)
    pages = []
    for i, page in enumerate(doc, start=1):
        # sort=True scrambles rotated (landscape) pages, so keep PDF reading order
        text = clean(page.get_text("text"))
        tabs, merges = tables(page) if len(text) >= MIN_CHARS else ([], [])
        pages.append({
            "page": i,
            "text": text,
            "n_chars": len(text),
            "low_text": len(text) < MIN_CHARS,  # in these plans: maps / blank pages
            "tables": tabs,
            "table_merges": merges,
        })
    return {
        "plan_id": f"{pdf.parent.name}/{pdf.stem}",
        "state": pdf.parent.name,
        "district": pdf.stem.replace("_", " "),
        "census_code_2011": meta.get("census_code_2011"),
        "map_district_2011": meta.get("map_district_2011"),
        "plan_year": meta.get("year_in_filename"),
        "source_url": meta.get("url"),
        "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "n_pages": len(pages),
        "extractor": f"pymupdf {pymupdf.__version__}",
        "pages": pages,
    }


def main():
    links = load_links()
    rows = []
    for pdf in sorted(PLANS.glob("*/*.pdf")):
        state, district = pdf.parent.name, pdf.stem.replace("_", " ")
        meta = links.get((state, district)) or links.get((state, pdf.stem)) or {}
        if not meta:
            print(f"warning: no links.csv row for {state}/{district}")
        rec = extract(pdf, meta)
        out = OUT / state / f"{pdf.stem}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append({
            "plan_id": rec["plan_id"], "state": state, "district": rec["district"],
            "census_code_2011": rec["census_code_2011"], "plan_year": rec["plan_year"],
            "n_pages": rec["n_pages"],
            "n_low_text_pages": sum(p["low_text"] for p in rec["pages"]),
            "n_chars": sum(p["n_chars"] for p in rec["pages"]),
            "json": out.relative_to(OUT).as_posix(),
        })
    with open(OUT / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} plans, {sum(r['n_pages'] for r in rows)} pages -> {OUT}")


if __name__ == "__main__":
    main()
