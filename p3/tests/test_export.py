"""Tests for the hand-off to Persons 4 and 5 (p3/export.py) and the planted-claim lookup.
    python -m pytest p3/tests"""
import json

from p3.export import rule_fields
from p3.planted import ROOT, planted_claims


def claim(**kw):
    base = {"claim_type": None, "metric": None, "season": None, "crop": None, "recommended_crops": []}
    return {**base, **kw}


def test_rule_types_follow_decision_rules():
    assert rule_fields(claim(claim_type="rainfall_normal", metric="rainfall_mm"))[0] == "rainfall_normal"
    assert rule_fields(claim(claim_type="monsoon_onset", season="sw_monsoon"))[0] == "onset_normal"
    assert rule_fields(claim(claim_type="monsoon_onset", season="ne_monsoon"))[0] is None
    assert rule_fields(claim(claim_type="contingency_measure"))[0] is None
    assert rule_fields(claim(claim_type="crop_production"))[0] is None


def test_open_questions_are_flagged_not_hidden():
    assert rule_fields(claim(claim_type="rainfall_normal", metric="rainy_days"))[2]
    assert rule_fields(claim(claim_type="sowing_window", season="rabi"))[2]
    assert rule_fields(claim(claim_type="sowing_window", season="kharif"))[2] is None


def test_no_change_and_fallow_are_not_crops_to_look_up():
    t, crops, note = rule_fields(claim(claim_type="contingency_crop_change", recommended_crops=["No change"]))
    assert t is None and crops == [] and note
    t, crops, _ = rule_fields(claim(claim_type="contingency_crop_change",
                                    recommended_crops=["Fallow", "Sunflower", "sunflower"]))
    assert t == "recommended_action" and crops == ["Sunflower"]


def test_crop_area_gets_crop_data_name():
    assert rule_fields(claim(claim_type="crop_area", crop="Lentil"))[:2] == ("normal_crop", ["Masoor"])


def test_planted_sowing_window_matches_start_and_end():
    # Chitradurga: planted Groundnut 7/2-9/2; Ragi on the same page also starts 7/2 but is not planted
    cs = [json.loads(l) for l in (ROOT / "claims_rules_planted" / "Karnataka" / "Chitradurga.jsonl")
          .read_text(encoding="utf-8").splitlines()]
    page = next(c["page"] for c in cs if c["claim_type"] == "sowing_window")
    found = planted_claims({"plan_id": "Karnataka/Chitradurga@planted", "page": str(page),
                            "error_type": "sowing_shift_6w", "claim_type": "sowing_window",
                            "planted_value": "7/2-9/2"})
    assert len(found) == 1 and "Groundnut" in found[0]["statement"]
