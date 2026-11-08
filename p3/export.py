"""Person 3: hand claims to Person 4 (agents) and Person 5 (scoring) in their folder layout.

Writes, per district (Census 2011 code):
  data/processed/claims/<code>.jsonl           claims from the real plan
  data/processed/claims_planted/<code>.jsonl   claims from the planted copy (no answers in it)
  data/processed/eval/planted_answers.csv      answer key + the planted claim's claim_id
                                               (Person 5 only; never give it to the agents)

Each claim is the stored claim (p3/claims/schema.py) plus three fields for
contracts/decision_rules.md:
  rule_type   which decision rule applies (rainfall_normal, onset_normal, normal_crop,
              sowing_window, recommended_action), or null if no rule covers the claim
  rule_crops  crop-data names (crop_name column) the rule should look up, for normal_crop
              and recommended_action; "No change" / "Fallow" are left out
  rule_note   why a claim has no rule, or what the team still has to settle for it

    python -m p3.export              # the 5 pilot districts
    python -m p3.export --all        # all 105
"""
import argparse
import csv
import json
from pathlib import Path

from .crops import to_crop_data_name
from .planted import planted_claims

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
NOT_CROPS = {"nochange", "fallow"}


def rule_fields(c):
    """rule_type, rule_crops, rule_note for one claim."""
    t = c["claim_type"]
    if t == "rainfall_normal":
        return ("rainfall_normal", [],
                "rainy days: the rule is written for rainfall amount" if c["metric"] == "rainy_days" else None)
    if t == "monsoon_onset":
        if c["season"] == "sw_monsoon":
            return "onset_normal", [], None
        return None, [], "onset is defined only for the SW monsoon (from 1 June)"
    if t == "sowing_window":
        return ("sowing_window", [],
                "rabi window compared with the June monsoon onset: team to decide" if c["season"] == "rabi" else None)
    if t == "crop_area":
        name = to_crop_data_name(c["crop"])
        return ("normal_crop", [name], None) if name else (None, [], "crop not in the crop data")
    if t == "contingency_crop_change":
        crops = [c2 for x in c["recommended_crops"]
                 if "".join(ch for ch in x.lower() if ch.isalpha()) not in NOT_CROPS
                 and (c2 := to_crop_data_name(x))]
        crops = list(dict.fromkeys(crops))
        if crops:
            return "recommended_action", crops, None
        return None, [], "no recommended crop to look up (No change / Fallow / not in crop data)"
    return None, [], "no decision rule for this claim type"


def tagged(path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        c["rule_type"], c["rule_crops"], c["rule_note"] = rule_fields(c)
        rows.append(c)
    return rows


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def main():
    from .claims.extract import PILOT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="all 105 plans instead of the 5 pilots")
    a = ap.parse_args()
    plans = (sorted(p.relative_to(ROOT / "claims_rules").with_suffix("").as_posix()
                    for p in (ROOT / "claims_rules").glob("*/*.jsonl")) if a.all else PILOT)
    answers = list(csv.DictReader(open(ROOT / "planted_text" / "answers.csv", encoding="utf-8")))
    key_rows, by_code = [], {}  # Thane and Palghar share Census 2011 code 517: one file, both plans
    for plan_id in plans:
        real = tagged(ROOT / "claims_rules" / f"{plan_id}.jsonl")
        code = real[0]["census_code_2011"]
        out = by_code.setdefault(code, {"claims": [], "claims_planted": []})
        out["claims"] += real
        planted = ROOT / "claims_rules_planted" / f"{plan_id}.jsonl"
        if planted.exists():
            out["claims_planted"] += tagged(planted)
        for ans in answers:
            if ans["plan_id"] == f"{plan_id}@planted":
                ids = [c["claim_id"] for c in planted_claims(ans)]
                key_rows.append({"census_code_2011": code, "planted_claim_id": ";".join(ids), **ans})
        n_rule = sum(c["rule_type"] is not None for c in real)
        print(f"{code} {plan_id}: {len(real)} claims, {n_rule} with a decision rule")
    for code, out in by_code.items():
        for folder, rows in out.items():
            if rows:
                write_jsonl(OUT / folder / f"{code}.jsonl", rows)
    path = OUT / "eval" / "planted_answers.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(key_rows[0]))
        w.writeheader()
        w.writerows(key_rows)
    print(f"{len(key_rows)} planted errors -> {path}")


if __name__ == "__main__":
    main()
