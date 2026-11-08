"""Person 3, Tasks 3-4: planted-claim generator (test data for check 2).

Takes a plan's real claims, plants known errors in a COPY of the plan text, and records
the answers. The planted copies then go through the Claim Extractor like any plan, so
check 2 tests extraction and checking together.

    python -m p3.planted --plans Karnataka/Udupi      # needs claims/<plan>.jsonl
    python -m p3.planted --pilot

Writes planted_text/<State>/<District>.json (plan_text format, plan_id gets "@planted")
and planted_text/answers.csv (one row per planted error, expected label "contradicted").

Error types (each one large enough that the data should clearly contradict it):
  crop_not_grown   a crop in 1.7 (area) or 2.x (recommended crop) replaced by a field crop
                   the district has had no area under in any year 1997-2023
  sowing_shift_6w  a sowing window (1.12) moved 6 weeks later
  onset_shift_4w   the normal SW monsoon onset week (1.2) moved 4 weeks later
  rainfall_x1.6    a normal rainfall figure (1.2) multiplied by 1.6 (x0.6 if > 2000 mm)
"""
import argparse
import copy
import csv
import json
import random
import re
from pathlib import Path

from .claims.checks import norm
from .crops import district_crops, key, state_field_crops, to_crop_data_name

ROOT = Path(__file__).resolve().parents[1]
PLAN_TEXT = ROOT / "plan_text"
CLAIMS = ROOT / "claims_rules"  # rule-based claims; claims/ holds LLM comparison runs
OUT = ROOT / "planted_text"
SEED = 2026
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
ANSWER_FIELDS = ["planted_id", "plan_id", "page", "error_type", "source_claim_id",
                 "claim_type", "original_text", "planted_text", "original_value",
                 "planted_value", "expected_label", "note", "extracted"]


def shift_week(month, week, weeks):
    """Move (month, week-of-month 1-4) by `weeks`, treating each month as 4 weeks."""
    idx = (month - 1) * 4 + (min(week, 4) - 1) + weeks
    return idx // 4 % 12 + 1, idx % 4 + 1


def week_text(month, week):
    return f"{ORD[week]} week of {MONTH_NAMES[month - 1]}"


def range_text(s, e):
    return week_text(*s) if s == e else f"{week_text(*s)} to {week_text(*e)}"


def plan_style(crop_data_name):
    """How a plan would write a crop: 'Castor Seed' -> 'Castor', 'Cowpea(Lobia)' -> 'Cowpea'."""
    from .crops import ALIASES
    first = ALIASES.get(crop_data_name, [crop_data_name])[0]
    return first[:1].upper() + first[1:]


def replace_once(page_text, old, new):
    """Replace `old` in the page once. Returns new text or None if `old` is not unique."""
    if page_text.count(old) != 1:
        return None
    return page_text.replace(old, new)


def find_fragment(page_text, frag):
    """The exact substring of the page that matches a quote fragment (whitespace may differ)."""
    if frag in page_text:
        return frag
    # quote fragments are whitespace-normalised; map back onto the raw page text
    words = norm(frag).split(" ")
    pat = r"\s+".join(re.escape(w) for w in words)
    m = list(re.finditer(pat, page_text))
    return m[0].group(0) if len(m) == 1 else None


def candidates(claims, plan):
    """Yield (error_type, claim, old_substring, new_substring, original, planted, note)."""
    st, dist = plan["state"], plan["district"]
    grown = {key(c) for c in district_crops(st, dist)}
    pool = [c for c in state_field_crops(st) if key(c) not in grown]
    if not pool:  # district grows every common crop of its state: use other states' crops
        pool = [c for s in ("Karnataka", "Maharashtra", "Rajasthan", "Telangana")
                for c in state_field_crops(s) if key(c) not in grown]
    pool = sorted(set(pool))
    pages = {p["page"]: p["text"] for p in plan["pages"]}

    for c in claims:
        text = pages[c["page"]]
        t = c["claim_type"]
        if t == "crop_area" and c.get("crop") and pool and to_crop_data_name(c["crop"]):
            frag = next((f for f in c["quote_parts"] if key(f) == key(c["crop"])), None)
            old = find_fragment(text, frag) if frag else None
            if old:
                new = plan_style(random.choice(pool))
                yield ("crop_not_grown", c, old, new, c["crop"], new,
                       f"{new}: no area in {dist} 1997-2023")
        elif t == "contingency_crop_change" and pool:
            recs = [r for r in c.get("recommended_crops", []) if to_crop_data_name(r)]
            # the recommendation fragments come after the normal-crop fragment in quote_parts
            parts = c["quote_parts"]
            nc = next((i for i, f in enumerate(parts) if norm(f) == norm(c.get("normal_crop") or "")), None)
            after = parts[nc + 1:] if nc is not None else []
            frag = next((f for f in after for r in recs if key(r) in key(f)
                         and key(r) != key(c.get("normal_crop") or "")), None)
            old = find_fragment(text, frag) if frag else None
            if old:
                new = plan_style(random.choice(pool))
                yield ("crop_not_grown", c, old, new, frag, new,
                       f"recommended {new}: no area in {dist} 1997-2023")
        elif t == "sowing_window" and c.get("start_week") and c.get("end_week"):
            frag = next((f for f in c["quote_parts"]
                         if MONTH_NAMES[c["start_month"] - 1][:3].lower() in f.lower()), None)
            old = find_fragment(text, frag) if frag else None
            if old:
                s = shift_week(c["start_month"], c["start_week"], 6)
                e = shift_week(c["end_month"], c["end_week"], 6)
                new = range_text(s, e)
                yield ("sowing_shift_6w", c, old, new,
                       f"{c['start_month']}/{c['start_week']}-{c['end_month']}/{c['end_week']}",
                       f"{s[0]}/{s[1]}-{e[0]}/{e[1]}", "month/week-of-month")
        elif t == "monsoon_onset" and c.get("season") == "sw_monsoon" and c.get("start_week"):
            frag = next((f for f in c["quote_parts"] if "week" in f.lower()), None)
            old = find_fragment(text, frag) if frag else None
            if old:
                s = shift_week(c["start_month"], c["start_week"], 4)
                yield ("onset_shift_4w", c, old, week_text(*s).replace("week", "Week"),
                       f"{c['start_month']}/{c['start_week']}", f"{s[0]}/{s[1]}", "")
        elif (t == "rainfall_normal" and c.get("metric") == "rainfall_mm"
              and c.get("value") and c["value"] >= 50):
            v = c["value"]
            frag = next((f for f in c["quote_parts"] if norm(f) in (f"{v:g}", f"{v:.1f}")), None)
            old = find_fragment(text, frag) if frag else None
            if old:
                factor = 0.6 if v > 2000 else 1.6
                new = f"{round(v * factor)}"
                yield (f"rainfall_x{factor}", c, old, new, v, float(new), c.get("season", ""))


def plant_plan(plan_id, per_type=2):
    plan = json.loads((PLAN_TEXT / f"{plan_id}.json").read_text(encoding="utf-8"))
    claims_file = CLAIMS / f"{plan_id}.jsonl"
    claims = [json.loads(l) for l in claims_file.read_text(encoding="utf-8").splitlines()]
    random.seed(f"{SEED}:{plan_id}")

    cands = list(candidates(claims, plan))
    random.shuffle(cands)
    planted = copy.deepcopy(plan)
    pages = {p["page"]: p for p in planted["pages"]}
    used, taken, answers = set(), {}, []
    for etype, c, old, new, orig, plant, note in cands:
        base = etype.split("_x")[0]
        if taken.get(base, 0) >= per_type or (c["page"], old) in used:
            continue
        page = pages[c["page"]]
        new_text = replace_once(page["text"], old, new)
        if new_text is None:
            continue
        page["text"] = new_text
        # the rebuilt tables hold the same cell with whitespace collapsed: edit them too
        cell = re.sub(r"\s+", " ", old).strip()  # tables only collapse whitespace (keep '–' etc.)
        page["tables"] = [re.sub(rf"(?<=\| ){re.escape(cell)}(?= \|)", new, t, count=1)
                          if cell in t else t for t in page.get("tables", [])]
        if not any(new in t for t in page["tables"]):  # the fragment is part of a larger cell
            i = next((i for i, t in enumerate(page["tables"]) if cell in t), None)
            if i is not None:
                page["tables"][i] = page["tables"][i].replace(cell, new, 1)
        used.add((c["page"], old))
        taken[base] = taken.get(base, 0) + 1
        answers.append({
            "planted_id": f"{plan_id}@planted#{len(answers) + 1}", "plan_id": f"{plan_id}@planted",
            "page": c["page"], "error_type": etype, "source_claim_id": c["claim_id"],
            "claim_type": c["claim_type"], "original_text": old, "planted_text": new,
            "original_value": orig, "planted_value": plant,
            "expected_label": "contradicted", "note": note})

    planted["plan_id"] = f"{plan_id}@planted"
    planted["planted_from"] = plan_id
    planted["n_planted"] = len(answers)
    out = OUT / f"{plan_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(planted, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{plan_id}: planted {len(answers)} errors "
          f"({', '.join(f'{k} {v}' for k, v in sorted(taken.items()))})")
    return answers


def write_answers(rows):
    path = OUT / "answers.csv"
    old = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            done = {r["plan_id"] for r in rows}
            old = [r for r in csv.DictReader(f) if r["plan_id"] not in done]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ANSWER_FIELDS)
        w.writeheader()
        w.writerows(old + rows)


def planted_claims(a):
    """The claims in claims_rules_planted/ that carry planted error `a` (a row of answers.csv)."""
    f = ROOT / "claims_rules_planted" / f"{a['plan_id'].replace('@planted', '')}.jsonl"
    cs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []
    pv, et = a["planted_value"], a["error_type"]
    return [c for c in cs
            if c["page"] == int(a["page"]) and c["claim_type"] == a["claim_type"] and (
                (et == "crop_not_grown" and any(key(pv) in key(x or "")
                                                for x in [c.get("crop")] + c.get("recommended_crops", [])))
                or (et.startswith("rainfall") and c.get("value") == float(pv))
                or (et == "onset_shift_4w" and f"{c['start_month']}/{c['start_week']}" == pv)
                or (et == "sowing_shift_6w"
                    and f"{c['start_month']}/{c['start_week']}-{c['end_month']}/{c['end_week']}" == pv))]


def verify():
    """Mark each planted error extracted=yes/no, using claims_rules_planted/ (run rules --planted first)."""
    path = OUT / "answers.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    for a in rows:
        a["extracted"] = "yes" if planted_claims(a) else "no"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ANSWER_FIELDS)
        w.writeheader()
        w.writerows(rows)
    n = sum(a["extracted"] == "yes" for a in rows)
    print(f"planted errors re-extracted: {n}/{len(rows)}")


def main():
    from .claims.extract import PILOT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plans", nargs="+")
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--all", action="store_true")
    g.add_argument("--verify", action="store_true", help="mark answers.csv extracted=yes/no")
    ap.add_argument("--per-type", type=int, default=2, help="max errors per error type per plan")
    a = ap.parse_args()
    if a.verify:
        return verify()
    if a.all:
        plans = sorted(p.relative_to(CLAIMS).with_suffix("").as_posix()
                       for p in CLAIMS.glob("*/*.jsonl") if not p.parent.name.startswith("_"))
    else:
        plans = PILOT if a.pilot else a.plans
    rows = []
    for pid in plans:
        if not (CLAIMS / f"{pid}.jsonl").exists():
            print(f"skip {pid}: no claims yet")
            continue
        rows += plant_plan(pid, a.per_type)
    write_answers(rows)
    print(f"{len(rows)} planted errors -> {OUT / 'answers.csv'}")


if __name__ == "__main__":
    main()
