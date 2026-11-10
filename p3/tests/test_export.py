"""Tests for the hand-off to Persons 4 and 5 (p3/export.py) and the planted-claim lookup.
    python -m pytest p3/tests"""
import csv
import json

from p3.export import rule_fields
from p3.planted import ROOT, planted_claims


def claim(**kw):
    base = {"claim_type": None, "metric": None, "season": None, "crop": None, "recommended_crops": [],
            "state": "Karnataka"}
    return {**base, **kw}


def answers():
    return list(csv.DictReader(open(ROOT / "planted_text" / "answers.csv", encoding="utf-8")))


def test_rule_types_follow_decision_rules_v2():
    assert rule_fields(claim(claim_type="rainfall_normal", metric="rainfall_mm"))[:3] == \
        ("rainfall_normal", [], "checkable")
    assert rule_fields(claim(claim_type="rainfall_normal", metric="rainy_days"))[2] == "checkable"
    assert rule_fields(claim(claim_type="monsoon_onset", season="sw_monsoon"))[0] == "onset_normal"
    assert rule_fields(claim(claim_type="monsoon_onset", season="ne_monsoon"))[2] == "not_checkable"
    assert rule_fields(claim(claim_type="contingency_measure"))[:3] == (None, [], "not_checkable")
    assert rule_fields(claim(claim_type="crop_production"))[2] == "not_checkable"


def test_rabi_windows_are_not_enough_evidence_by_rule():
    assert rule_fields(claim(claim_type="sowing_window", season="rabi"))[2] == "nee_by_rule"
    assert rule_fields(claim(claim_type="sowing_window", season="kharif"))[2] == "checkable"


def test_crops_without_recent_data_are_not_enough_evidence():
    # Karnataka's crop data has mango only up to 2003-04
    assert rule_fields(claim(claim_type="crop_area", crop="Mango"))[2] == "nee_by_rule"
    assert rule_fields(claim(claim_type="crop_area", crop="Isabgol"))[2] == "nee_by_rule"  # not in the data
    assert rule_fields(claim(claim_type="crop_area", crop="Lentil"))[:3] == ("normal_crop", ["Masoor"], "checkable")


def test_no_change_and_fallow_are_not_crops_to_look_up():
    t, crops, status, note = rule_fields(claim(claim_type="contingency_crop_change", recommended_crops=["No change"]))
    assert t is None and crops == [] and status == "not_checkable" and note
    t, crops, status, _ = rule_fields(claim(claim_type="contingency_crop_change",
                                            recommended_crops=["Fallow", "Sunflower", "sunflower"]))
    assert (t, crops, status) == ("recommended_action", ["Sunflower"], "checkable")


def test_every_planted_error_is_checkable_under_v2():
    rows = answers()
    assert rows and all(a["extracted"] == "yes" for a in rows)
    for a in rows:
        found = planted_claims(a)
        assert found and all(rule_fields(c)[2] == "checkable" for c in found), a["planted_id"]
        assert a["expected_reason"] == ("plan_figure" if a["error_type"].startswith(("rainfall", "onset"))
                                        else "recent_data")


def test_planted_sowing_window_matches_start_and_end():
    # a claim on the same page that only shares the start week is not the planted one
    for a in answers():
        if a["error_type"] == "sowing_shift_6w":
            for c in planted_claims(a):
                assert f"{c['start_month']}/{c['start_week']}-{c['end_month']}/{c['end_week']}" == a["planted_value"]


def test_planted_match_ignores_unchanged_claims():
    # Jodhpur p6: a real wheat window once equalled the planted value by chance; it was never changed
    real = {}
    for line in (ROOT / "claims_rules" / "Rajasthan" / "Jodhpur.jsonl").read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        real[c["claim_id"]] = c["quote_parts"]
    for a in answers():
        if a["plan_id"] == "Rajasthan/Jodhpur@planted":
            assert all(real.get(c["claim_id"]) != c["quote_parts"] for c in planted_claims(a))
