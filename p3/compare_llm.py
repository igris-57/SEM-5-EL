"""Person 3: compare the rule-based extractor with Gemini on a small page sample.

The free Gemini tier allows about 20 requests a day, so this runs on 9 held-out pages that
cover every table type (rainfall, area, production, sowing + hazards, drought tables).
Both extractors' claims go through the same checks; matched claims are compared field by field.

    python -m p3.compare_llm          # -> review/llm_comparison.csv + a printed summary
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "review" / "llm_comparison.csv"
PAGES = [  # (plan, page, what is on it) -- all from review/heldout_plans.txt
    ("Karnataka/Kolar", 1, "rainfall / onset"),
    ("Maharashtra/Nashik", 3, "crop area"),
    ("Rajasthan/Barmer", 4, "production"),
    ("Karnataka/Belgaum", 5, "production + sowing"),
    ("Maharashtra/Thane", 7, "hazards"),
    ("Maharashtra/Buldhana", 12, "delayed onset"),
    ("Maharashtra/Nanded", 10, "delayed onset"),
    ("Rajasthan/Jaipur", 14, "dry spell + mid-season"),
    ("Maharashtra/Sindhudurg", 19, "terminal drought"),
]


def key(c):
    """What a claim is about, so the two extractors' claims can be paired."""
    t = c["claim_type"]
    if t in ("rainfall_normal", "monsoon_onset", "monsoon_cessation"):
        return (t, c.get("season"), c.get("metric"))
    if t == "hazard_proneness":
        return (t, c.get("hazard"))
    if t.startswith("contingency"):
        from p3.crops import key as k
        return (t, k(c.get("normal_crop") or ""), c.get("delay_weeks"), c.get("condition"),
                k(c.get("farming_situation") or "")[:12])
    from p3.crops import to_crop_data_name
    return (t, to_crop_data_name(c.get("crop")) or c.get("crop"), c.get("season"),
            c.get("metric"), c.get("water_regime"))


VALUE_FIELDS = ["value", "start_month", "start_week", "end_month", "end_week", "frequency",
                "recommended_crops"]


def main():
    from p3.claims.extract import extract_page
    from p3.claims.gemini import GeminiLLM
    llm = GeminiLLM(rpm=8, cache_dir=ROOT / "claims" / "_cache")
    rows, totals = [], {"pages": 0, "llm_ok": 0, "llm_rejected": 0, "rules": 0, "both": 0,
                        "agree": 0, "llm_only": 0, "rules_only": 0, "in_tokens": 0, "out_tokens": 0}
    for plan_id, page_no, what in PAGES:
        plan = json.loads((ROOT / "plan_text" / f"{plan_id}.json").read_text(encoding="utf-8"))
        page = plan["pages"][page_no - 1]
        prev = plan["pages"][page_no - 2]["text"] if page_no > 1 else ""
        ok, bad, retried, usage = extract_page(llm, plan, page, prev)
        llm_c = [c.model_dump(mode="json") for c, _match in ok]
        rule_c = [json.loads(l) for l in (ROOT / "claims_rules" / f"{plan_id}.jsonl")
                  .read_text(encoding="utf-8").splitlines()]
        rule_c = [c for c in rule_c if c["page"] == page_no]
        lk, rk = {}, {}
        for c in llm_c:
            lk.setdefault(key(c), c)
        for c in rule_c:
            rk.setdefault(key(c), c)
        totals["pages"] += 1
        totals["llm_ok"] += len(llm_c)
        totals["llm_rejected"] += len(bad)
        totals["rules"] += len(rule_c)
        totals["in_tokens"] += usage.get("in_tokens") or 0
        totals["out_tokens"] += usage.get("out_tokens") or 0
        for k in sorted(set(lk) | set(rk), key=str):
            a, b = rk.get(k), lk.get(k)
            if a and b:
                diff = [f for f in VALUE_FIELDS if (a.get(f) or None) != (b.get(f) or None)]
                status = "agree" if not diff else "differ: " + ", ".join(diff)
                totals["both"] += 1
                totals["agree"] += not diff
            else:
                status = "rules only" if a else "llm only"
                totals["rules_only" if a else "llm_only"] += 1
            rows.append({"plan_id": plan_id, "page": page_no, "content": what, "claim_type": k[0],
                         "status": status, "rules_statement": a["statement"] if a else "",
                         "llm_statement": b["statement"] if b else ""})
        print(f"{plan_id} p{page_no} ({what}): rules {len(rule_c)}, llm {len(llm_c)} ok / "
              f"{len(bad)} rejected{' (retried)' if retried else ''}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(totals, indent=1))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
