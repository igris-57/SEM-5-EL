"""Person 3, Task 3b/5: plan figures (test data for check 1).

One row per number the plan states about its own district, taken from the rule-based
claims: normal rainfall and rainy days per season, onset and cessation weeks, sowing
windows, and crop areas with their rank in the plan (`crop_area_part` = only the irrigated,
rainfed or one-season part, for plans with no single total). Person 5's check 1 compares these
with what the evidence tools compute from IMD rain and crop data.

    python -m p3.figures          # -> plan_figures.csv
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "claims_rules"
OUT = ROOT / "plan_figures.csv"
FIELDS = ["plan_id", "census_code_2011", "figure", "season", "crop", "crop_data_name",
          "water_regime", "value", "unit", "rank_in_plan", "start_month", "start_week",
          "end_month", "end_week", "ref_year", "page", "claim_id", "quote"]
FIGURE = {("rainfall_normal", "rainfall_mm"): ("normal_rainfall", "mm"),
          ("rainfall_normal", "rainy_days"): ("normal_rainy_days", "days"),
          ("monsoon_onset", None): ("normal_onset", "month/week"),
          ("monsoon_cessation", None): ("normal_cessation", "month/week"),
          ("sowing_window", None): ("sowing_window", "month/week"),
          ("crop_area", "area_000ha"): ("crop_area", "'000 ha")}


def main():
    from .crops import to_crop_data_name
    rows = []
    for f in sorted(CLAIMS.glob("*/*.jsonl")):
        if f.parent.name.startswith("_"):
            continue
        claims = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
        # only whole-crop totals are ranked; an irrigated-only, rainfed-only or one-season area
        # (plans that give no single total) is a separate figure so it is never compared as a total
        part = lambda c: c["claim_type"] == "crop_area" and (c.get("water_regime") or c.get("season"))
        areas = sorted((c for c in claims if c["claim_type"] == "crop_area" and not part(c)),
                       key=lambda c: -c["value"])
        rank = {c["claim_id"]: i + 1 for i, c in enumerate(areas)}
        for c in claims:
            fig = FIGURE.get((c["claim_type"], c.get("metric"))) or FIGURE.get((c["claim_type"], None))
            if not fig:
                continue
            if part(c):
                fig = ("crop_area_part", fig[1])
            rows.append({
                "plan_id": c["plan_id"], "census_code_2011": c["census_code_2011"],
                "figure": fig[0], "season": c.get("season") or "", "crop": c.get("crop") or "",
                "crop_data_name": to_crop_data_name(c.get("crop")) or "",
                "water_regime": c.get("water_regime") or "",
                "value": "" if c.get("value") is None else c["value"],
                "unit": fig[1], "rank_in_plan": rank.get(c["claim_id"], ""),
                "start_month": c.get("start_month") or "", "start_week": c.get("start_week") or "",
                "end_month": c.get("end_month") or "", "end_week": c.get("end_week") or "",
                "ref_year": c.get("ref_year") or "", "page": c["page"], "claim_id": c["claim_id"],
                "quote": " | ".join(c["quote_parts"])})
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"{len(rows)} plan figures from {len({r['plan_id'] for r in rows})} plans -> {OUT}")
    print(dict(Counter(r["figure"] for r in rows)))


if __name__ == "__main__":
    main()
