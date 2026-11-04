"""Offline tests for the Claim Extractor (no API key needed).  python -m pytest p3/tests"""
import json
from pathlib import Path

from p3.claims.checks import check_claim, quote_match
from p3.claims.extract import extract_page, parse
from p3.claims.schema import Claim

ROOT = Path(__file__).resolve().parents[2]
UDUPI = json.loads((ROOT / "plan_text/Karnataka/Udupi.json").read_text(encoding="utf-8"))
P1 = UDUPI["pages"][0]["text"]
P7 = UDUPI["pages"][6]["text"]
P9 = UDUPI["pages"][8]["text"]

RAIN = {"claim_type": "rainfall_normal", "statement": "Normal SW monsoon rainfall is 3273 mm.",
        "quote_parts": ["SW monsoon (June-Sep):", "3273"],
        "season": "sw_monsoon", "metric": "rainfall_mm", "value": 3273}


class FakeLLM:
    model = "fake"

    def __init__(self, *answers):
        self.answers = list(answers)

    def generate_json(self, system, prompt, schema):
        return json.dumps({"claims": self.answers.pop(0)}), {"in_tokens": 1, "out_tokens": 1,
                                                            "seconds": 0, "cached": False}


def test_good_claim_passes():
    problems, match = check_claim(Claim(**RAIN), P1)
    assert problems == [] and match == "exact"


def test_invented_number_rejected():
    problems, _ = check_claim(Claim(**{**RAIN, "value": 3000}), P1)
    assert any("value=3000" in p for p in problems)


def test_quote_not_on_page_rejected():
    problems, _ = check_claim(Claim(**{**RAIN, "quote_parts": ["SW monsoon rainfall 3273 mm"]}), P1)
    assert any("quote not on page" in p for p in problems)


def test_loose_match_for_split_words():
    # page has "4th week of October t o 2 nd week of"
    assert quote_match("4th week of October to 2nd week of", P7) == "loose"


def test_onset_week_and_month_checked():
    c = Claim(claim_type="monsoon_onset", statement="Normal SW monsoon onset is 1st week of June.",
              quote_parts=["SW monsoon (June-Sep):", "1st Week of June"],
              season="sw_monsoon", start_month=6, start_week=1)
    assert check_claim(c, P1)[0] == []
    wrong = c.model_copy(update={"start_month": 7})
    assert any("not what the quote says" in p for p in check_claim(wrong, P1)[0])


def test_dates_parser():
    from p3.claims.dates import parse_point, parse_range
    assert parse_point("24th MW (June 11-17)") == (6, 2)
    assert parse_point("Delay by 2 weeks ( 3rd week of June )") == (6, 3)
    assert parse_range("2nd fortnight of June to 1st fortnight of July") == ((6, 3), (7, 2))
    assert parse_range("4th week of October t o 2 nd week of November") == ((10, 4), (11, 2))
    assert parse_range("15th Dec-15th Jan (Onion)") == ((12, 3), (1, 3))


def test_missing_required_field_rejected():
    ok, bad = parse(json.dumps({"claims": [{**RAIN, "value": None}]}), P1)
    assert not ok and "needs value" in bad[0][1][0]


def test_delayed_onset_crop_change():
    raw = {"claim_type": "contingency_crop_change",
           "statement": "If the monsoon is delayed by 2 weeks, paddy stays paddy (no change).",
           "quote_parts": ["Delay by 2 weeks (", "Paddy", "No change"],
           "condition": "delayed_onset", "delay_weeks": 2, "normal_crop": "Paddy",
           "farming_situation": "Shallow, lateritic, acid soil", "recommended_crops": ["No change"]}
    ok, bad = parse(json.dumps({"claims": [raw]}), P9)
    assert len(ok) == 1 and not bad


def test_retry_fixes_bad_claim():
    llm = FakeLLM([{**RAIN, "value": 3000}], [RAIN])
    ok, bad, retried, usage = extract_page(llm, UDUPI, UDUPI["pages"][0], "")
    assert retried and len(ok) == 1 and not bad and usage["in_tokens"] == 2


def test_rules_udupi():
    from p3.claims.rules import extract_plan
    import p3.claims.rules as rules
    rules.OUT = Path(__file__).resolve().parent / "_tmp_rules"
    extract_plan("Karnataka/Udupi")
    cs = [json.loads(l) for l in (rules.OUT / "Karnataka/Udupi.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(c["claim_type"] == "rainfall_normal" and c["value"] == 3273 for c in cs)
    assert any(c["claim_type"] == "monsoon_onset" and (c["start_month"], c["start_week"]) == (6, 1) for c in cs)
    d4 = [c for c in cs if c["claim_type"] == "contingency_crop_change" and c["delay_weeks"] == 4]
    assert d4 and d4[0]["start_month"] == 7 and d4[0]["start_week"] == 1
    assert all(c["quote_match"] in ("exact", "loose") for c in cs)
