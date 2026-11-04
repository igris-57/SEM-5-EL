"""Person 3, Task 3a: hand-review workbook = the evaluation set for the extractor.

30 plans (the 5 pilots + 25 others, stratified by state), 10 claims each, stratified by
claim type -> ~300 claims to mark correct / wrong (precision). Plus one page per plan to
check for facts the extractor missed (recall).

    python -m p3.review               # -> review/claim_review.xlsx
    python -m p3.review --score       # after marking: precision / recall summary
    python -m p3.review --plans-file review/heldout_plans.txt --out review/claim_review_v2.xlsx
                                      # a held-out sheet (plans not used to fix the extractor)
"""
import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "claims_rules"
PLANS_PDF = ROOT / "DOCS" / "data" / "Main EL" / "data" / "plans"
OUT = ROOT / "review" / "claim_review.xlsx"
SEED = 2026
PER_STATE = {"Karnataka": 7, "Maharashtra": 8, "Rajasthan": 8, "Telangana": 2}
PER_PLAN = 10
ERROR_TYPES = "wrong value,wrong crop,wrong season/week,wrong condition,not a real claim,misread table,other"


def xl(text):
    """Excel refuses control characters; '\x01' is a tick in a symbol font (see rules.TICK)."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "[tick]", text or "")


def load(plan_id):
    return [json.loads(l) for l in (CLAIMS / f"{plan_id}.jsonl").read_text(encoding="utf-8").splitlines()]


def pick_plans():
    from .claims.extract import PILOT
    rng = random.Random(SEED)
    all_plans = sorted(p.relative_to(CLAIMS).with_suffix("").as_posix()
                       for p in CLAIMS.glob("*/*.jsonl") if not p.parent.name.startswith("_"))
    chosen = list(PILOT)
    for state, n in PER_STATE.items():
        pool = [p for p in all_plans if p.startswith(state + "/") and p not in PILOT and load(p)]
        chosen += sorted(rng.sample(pool, n))
    return chosen


def pick_claims(claims, rng):
    by_type = defaultdict(list)
    for c in claims:
        by_type[c["claim_type"]].append(c)
    for v in by_type.values():
        rng.shuffle(v)
    out, types = [], sorted(by_type)
    while len(out) < PER_PLAN and any(by_type.values()):
        for t in types:
            if by_type[t] and len(out) < PER_PLAN:
                out.append(by_type[t].pop())
    return out


def build(plans=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    rng = random.Random(SEED)
    plans = plans or pick_plans()
    wb = Workbook()
    ws = wb.active
    ws.title = "claims"
    head = ["review_id", "plan_id", "page", "claim_type", "statement", "quote (from the plan)",
            "open PDF", "CORRECT? (Y/N/?)", "error type (if N)", "correct value / note", "claim_id"]
    ws.append(head)
    for plan_id in plans:
        for c in pick_claims(load(plan_id), rng):
            ws.append([f"R{ws.max_row:03d}", plan_id, c["page"], c["claim_type"], xl(c["statement"]),
                       xl(" | ".join(c["quote_parts"])), "open", "", "", "", c["claim_id"]])
            pdf = (PLANS_PDF / f"{plan_id}.pdf").as_uri() + f"#page={c['page']}"
            cell = ws.cell(row=ws.max_row, column=7)
            cell.hyperlink, cell.style = pdf, "Hyperlink"
    n = ws.max_row
    yn = DataValidation(type="list", formula1='"Y,N,?"', allow_blank=True)
    et = DataValidation(type="list", formula1=f'"{ERROR_TYPES}"', allow_blank=True)
    ws.add_data_validation(yn)
    ws.add_data_validation(et)
    yn.add(f"H2:H{n}")
    et.add(f"I2:I{n}")

    ps = wb.create_sheet("pages (missed facts)")
    ps.append(["plan_id", "page", "open PDF", "claims the extractor found on this page",
               "how many facts did it MISS?", "examples of missed facts"])
    for plan_id in plans:
        claims = load(plan_id)
        pages = Counter(c["page"] for c in claims)
        page = rng.choice(sorted(pages))
        found = "\n".join(f"- {c['statement']}" for c in claims if c["page"] == page)
        ps.append([plan_id, page, "open", xl(found), "", ""])
        cell = ps.cell(row=ps.max_row, column=3)
        cell.hyperlink, cell.style = (PLANS_PDF / f"{plan_id}.pdf").as_uri() + f"#page={page}", "Hyperlink"

    info = wb.create_sheet("how to review")
    for line in [
        "How to review (about 1 minute per claim):",
        "1. Click 'open' to see the plan page. Find the quote.",
        "2. claims sheet: put Y if the statement says exactly what the plan says, N if anything is",
        "   wrong (value, crop, season, week, condition), ? if unsure. If N, pick an error type.",
        "3. pages sheet: read the whole page; count facts of these kinds that are NOT in the list:",
        "   normal rainfall / rainy days / onset / cessation, crop area, production / productivity,",
        "   sowing window, hazard tick, and drought contingency rows (crop change / measures).",
        "4. Save. Then run:  python -m p3.review --score",
        "Do not edit columns other than the yellow ones.",
    ]:
        info.append([line])

    yellow = PatternFill("solid", fgColor="FFF2CC")
    for sheet, cols, widths in ((ws, "HIJ", [8, 24, 6, 22, 70, 50, 8, 12, 18, 30, 30]),
                                (ps, "EF", [24, 6, 8, 90, 14, 50])):
        for i, w in enumerate(widths):
            sheet.column_dimensions[chr(65 + i)].width = w
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if cell.column_letter in cols:
                    cell.fill = yellow
        sheet.freeze_panes = "A2"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"{len(plans)} plans, {n - 1} claims, {ps.max_row - 1} pages -> {OUT}")


def score():
    from openpyxl import load_workbook
    wb = load_workbook(OUT)
    marks = [(r[3], (r[7] or "").strip().upper(), r[8]) for r in wb["claims"].iter_rows(min_row=2, values_only=True)]
    done = [m for m in marks if m[1] in ("Y", "N")]
    if not done:
        print("no claims marked yet")
        return
    y = sum(m[1] == "Y" for m in done)
    print(f"precision: {y}/{len(done)} = {y / len(done):.1%}  ({len(marks) - len(done)} unmarked/unsure)")
    for t in sorted({m[0] for m in done}):
        tt = [m for m in done if m[0] == t]
        print(f"  {t:26s} {sum(m[1] == 'Y' for m in tt)}/{len(tt)}")
    errs = Counter(m[2] for m in done if m[1] == "N")
    if errs:
        print("errors:", dict(errs))
    pages = [r for r in wb["pages (missed facts)"].iter_rows(min_row=2, values_only=True) if r[4] not in (None, "")]
    if pages:
        found = sum(len([l for l in (r[3] or "").split("\n") if l.strip()]) for r in pages)
        missed = sum(int(r[4]) for r in pages)
        print(f"recall (on {len(pages)} pages): {found}/{found + missed} = {found / (found + missed):.1%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--plans-file", help="one plan_id per line ('#' lines are comments)")
    ap.add_argument("--out", help=f"workbook path (default {OUT.relative_to(ROOT)})")
    a = ap.parse_args()
    if a.out:
        OUT = Path(a.out).resolve()
    plans = [l.strip() for l in open(a.plans_file, encoding="utf-8")
             if l.strip() and not l.startswith("#")] if a.plans_file else None
    score() if a.score else build(plans)
