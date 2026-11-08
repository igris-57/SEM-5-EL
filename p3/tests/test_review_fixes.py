"""Regression tests for the extractor bugs found in the claim review (review/claim_review.xlsx,
4 Nov 2026). Each test uses the real plan page where the bug was seen.
    python -m pytest p3/tests"""
import json
from functools import lru_cache
from pathlib import Path

import p3.claims.rules as rules
from p3.claims.dates import parse_range
from p3.crops import crop_mentions

TMP = Path(__file__).resolve().parent / "_tmp_rules"


@lru_cache(maxsize=None)
def claims(plan_id):
    rules.OUT = TMP
    rules.extract_plan(plan_id)
    return [json.loads(l) for l in (TMP / f"{plan_id}.jsonl").read_text(encoding="utf-8").splitlines()]


def pick(plan_id, **kw):
    return [c for c in claims(plan_id) if all(c.get(k) == v for k, v in kw.items())]


def test_fallow_keeps_the_rabi_crop():  # R210: 'Fallow-mustard' was stated as 'Fallow'
    assert crop_mentions("Fallow-Mustard (Bio-902 and Laxmi)/gram(Dahod Yellow)") == ["Fallow", "Mustard", "gram"]
    cs = pick("Rajasthan/Ajmer", claim_type="contingency_crop_change", normal_crop="Urdbean-mustard",
              delay_weeks=8)
    assert cs and all("mustard" in [r.lower() for r in c["recommended_crops"]] for c in cs)


def test_all_listed_crops_kept():  # R051 Setaria, R109 Cowpea typo, R139 intercrops
    assert crop_mentions("Redgram/Soyabean/Bajra/Sesamum /Setaria")[-1] == "Setaria"
    assert crop_mentions("Prefer CowpeC-152), Soybean")[0] == "Cowpe"
    assert crop_mentions("Cotton and Pigeon pea • Sorghum and Pigeonpea") == ["Cotton", "Pigeon pea", "Sorghum"]


def test_crop_change_statement_quotes_the_plan():  # R021: statement dropped 'Groundnut'
    c = pick("Maharashtra/Pune", claim_type="contingency_crop_change", normal_crop="Groundnut",
             delay_weeks=4, page=12)[0]
    assert "Groundnut + Pigeon pea" in c["statement"] and c["recommended_crops"] == ["Groundnut", "Pigeon pea"]


def test_merged_cells_cover_every_row():  # Bidar p11: one 'No change' spans 5 crop rows
    rows = {c["normal_crop"] for c in pick("Karnataka/Bidar", claim_type="contingency_crop_change",
                                           delay_weeks=2, page=11)}
    assert {"Redgram", "Blackgram", "Greengram", "Soyabean", "Sorghum"} <= rows


def test_irrigated_tables_not_called_terminal_drought():  # R121, R172
    for plan in ("Maharashtra/Ahmednagar", "Maharashtra/Satara"):
        assert not [c for c in claims(plan) if c.get("condition") and c["page"] == 16
                    and c["normal_crop"] in ("Rabi-Sorghum", "Kharif Sorghum")]


def test_paired_kharif_rabi_rows():  # R263 'Til | 7.5 | 506 | 9.24 Gram | 921', R244 'Guar/Gram'
    assert pick("Rajasthan/Sawai_Madhopur", claim_type="crop_production", crop="Gram", season="rabi",
                metric="productivity_kg_ha")[0]["value"] == 921
    assert not pick("Rajasthan/Sawai_Madhopur", claim_type="crop_production", crop="Til", season="rabi")
    assert pick("Rajasthan/Hanumangarh", claim_type="crop_production", crop="Guar", season="kharif",
                metric="production_000t")[0]["value"] == 109.0


def test_production_not_in_thousand_tonnes_skipped():  # Ratnagiri gives '00 MT
    assert not pick("Maharashtra/Ratnagiri", claim_type="crop_production", metric="production_000t")
    assert pick("Maharashtra/Ratnagiri", claim_type="crop_production", metric="productivity_kg_ha")


def test_rainy_days_skip_year_column():  # R107: 780 was the 2008 rainfall
    c = pick("Karnataka/Tumkur", claim_type="rainfall_normal", season="annual", metric="rainy_days")
    assert c and c[0]["value"] == 39


def test_sowing_crop_subheader():  # R138: rabi row has its own crops (Sorghum/Gram/Wheat)
    c = pick("Maharashtra/Chandrapur", claim_type="sowing_window", season="rabi", start_month=11)
    assert c and c[0]["crop"] == "Wheat"


def test_month_only_sowing_windows():  # Kodagu 'June to August'
    assert parse_range("June (Kharif) to August)") == ((6, 1), (8, 4))
    assert parse_range("June 2nd fort night") == ((6, 3), (6, 4))
    assert pick("Karnataka/Kodagu", claim_type="sowing_window", crop="Coffee")


def test_area_rows_without_crop_name_do_not_break_table():  # Kolhapur p3 kept only Sugarcane
    crops = {c["crop"] for c in pick("Maharashtra/Kolhapur", claim_type="crop_area")}
    assert {"Sugarcane", "Groundnut", "Soybean", "Wheat"} <= crops


def test_row_split_by_page_break_joined():  # R162 'of Nitrogen after restart of rains'
    c = pick("Maharashtra/Ratnagiri", claim_type="contingency_measure", normal_crop="Prosomillet",
             condition="mid_season_drought_vegetative")
    assert any("Apply split dose of Nitrogen after restart of rains" in m for m in c[0]["measures"])


def test_symbol_font_ticks():  # Chitradurga ticks come out as '\x01'; Chikmagalur has a stray one
    assert pick("Karnataka/Chitradurga", claim_type="hazard_proneness", hazard="drought")[0]["frequency"] == "regular"
    assert pick("Karnataka/Chikmagalur", claim_type="hazard_proneness", hazard="hailstorm")[0]["frequency"] == "none"


def test_area_total_split_into_irrigated_rainfed():  # Chamarajanagar has no single total column
    m = {c["water_regime"]: c["value"] for c in pick("Karnataka/Chamarajanagar", claim_type="crop_area", crop="Maize")}
    assert m == {"irrigated": 7.9, "rainfed": 55.0}


def test_cessation_after_year_rainfall_column():  # pilot Chitradurga: end dates were cut off
    c = {x["season"]: (x["start_month"], x["start_week"])
         for x in pick("Karnataka/Chitradurga", claim_type="monsoon_cessation")}
    assert c == {"sw_monsoon": (9, 4), "ne_monsoon": (12, 4)}


def test_unreadable_onset_does_not_shift_cessation():  # Haveri NE: onset 'September II FN to October I fortnight'
    assert not pick("Karnataka/Haveri", claim_type="monsoon_onset", season="ne_monsoon")
    assert pick("Karnataka/Haveri", claim_type="monsoon_cessation", season="ne_monsoon")[0]["start_month"] == 11


def test_roman_fortnights_and_half_ranges():  # pilot Gulbarga, Warangal 'July end'
    assert parse_range("Sept IInd FN to Oct 1st FN") == ((9, 3), (10, 2))
    assert parse_range("Ist FN to IInd FN October") == ((10, 1), (10, 4))
    assert parse_range("Mid June to July end") == ((6, 2), (7, 4))
    assert parse_range("June Ind FN to July IInd FN") is None  # ambiguous: no guess
    assert parse_range("2nd June to Ist week") is None         # end month missing: no guess


def test_condition_carries_over_repeated_header():  # pilot Gulbarga p15: 'Delay by 4 weeks' on p14
    assert {c["delay_weeks"] for c in pick("Karnataka/Gulbarga", claim_type="contingency_crop_change", page=15)} == {4}


def test_hazard_table_continued_on_next_page():  # pilot Chitradurga p7 -> p8
    assert pick("Karnataka/Chitradurga", claim_type="hazard_proneness", hazard="frost")[0]["page"] == 8


def test_production_table_continued_on_next_page():  # Gulbarga p7 (header repeated), Mahabubnagar p7 (no header)
    assert pick("Karnataka/Gulbarga", claim_type="crop_production", crop="Sunflower", season="kharif",
                metric="productivity_kg_ha")[0]["value"] == 380
    assert pick("Telangana/Mahabubnagar", claim_type="crop_production", crop="Sweet orange",
                metric="production_000t")[0]["page"] == 7


def test_rabi_parts_not_called_totals_and_leading_zero_skipped():
    # Karauli: 'Wheat | 62.7 | ...' sits under Rabi Irrigated, not a Total column
    assert not [c for c in pick("Rajasthan/Karauli", claim_type="crop_area") if c.get("water_regime")]
    assert rules.num("0640") is None and rules.num("01") == 1  # Osmanabad 'Potato 0640'


# ---- found in the held-out review (review/claim_review_v2.xlsx) ----

def test_heldout_dates():
    assert parse_range("4th week of May to 1st week ofJanuary") == ((5, 4), (1, 1))  # R019
    assert rules.parse_point("Delay by 8 week Aug 2nd week") == (8, 2)               # R101
    assert rules.parse_point("Delay by 2 weeks (Specify month)* (July 2nd wk)") == (7, 2)  # R261
    assert rules.parse_point("11th-20th June") == (6, 2)                              # R097
    assert rules.parse_point("18th to 24th June") == (6, 3)                           # R137
    assert parse_range("Oct. 15-25") == ((10, 3), (10, 4))                            # R288


def test_heldout_grand_total_and_paired_headers():
    assert pick("Maharashtra/Dhule", claim_type="crop_area", crop="Groundnut")[0]["value"] == 35.8  # R083
    assert pick("Rajasthan/Jaipur", claim_type="crop_area", crop="Pearlmillet")[0]["value"] == 295.7  # R233
    assert pick("Rajasthan/Sri_Ganganagar", claim_type="sowing_window", crop="Gram", season="rabi")   # R288
    assert pick("Rajasthan/Barmer", claim_type="sowing_window", crop="Isabgol")                       # R199
    assert pick("Maharashtra/Parbhani", claim_type="sowing_window", crop="Sorghum", season="rabi")    # R148


def test_heldout_negation_and_alternatives():
    assert rules.recommended("Avoid Soybean. Alternatively go for sole Tobacco") == ["Tobacco"]
    assert rules.recommended("No change / Soybean+ pigeon pea 4:2") == ["No change", "Soybean", "pigeon pea"]  # R141


def test_heldout_units():
    assert not [c for c in claims("Maharashtra/Akola") if c["claim_type"] == "crop_area" and c["value"] > 1000]
    assert not pick("Rajasthan/Sirohi", claim_type="crop_area", crop="Tomato")  # '(ha)' sub-heading


def test_ditto_variants_resolved():  # R042 '--do--'
    c = pick("Karnataka/Bellary", claim_type="contingency_measure", normal_crop="Sorghum+ Groundnut(2:4)",
             condition="early_dry_spell")
    assert c and not any("do" == m.strip("- ").lower() for m in c[0]["measures"])


# ---- independent review, 8 Nov 2026 ----

def test_month_ordinal_is_a_week():  # Hassan "start and end of normal sowing week", Gondia, Medak
    assert parse_range("May 2nd – May 3rd") == ((5, 2), (5, 3))
    assert parse_range("July 1st –July 4th") == ((7, 1), (7, 4))
    assert parse_range("June 2nd to July 2nd week") == ((6, 2), (7, 2))
    assert parse_range("June 15th to July 15th") == ((6, 3), (7, 3))  # a day stays a day


def test_week_ranges_and_spacing():
    assert parse_range("1-3rd week of Nov.") == ((11, 1), (11, 3))  # Kota, Baran, Bundi
    assert parse_range("14 th May to17 th June") == ((5, 2), (6, 3))  # Bagalkot
    assert parse_range("15h June – 10th July") == ((6, 3), (7, 2))  # Amravati
    assert parse_range("1st Nov. 20 th Nov") == ((11, 1), (11, 3))  # Beed


def test_roman_and_dashed_delay_dates():
    from p3.claims.dates import parse_point
    assert parse_point("Delay by 2 weeks June IV week (kharif sowing June II FN)") == (6, 4)  # Yadgir
    assert parse_point("Delay by 6 weeks August -2nd week") == (8, 2)  # Belgaum
    assert parse_point("Delay by 8 weeks (3rd week of` August)") == (8, 3)  # Banswara


def test_pali_start_and_end_rows_make_one_window():
    cs = pick("Rajasthan/Pali", claim_type="sowing_window")
    assert len(cs) == 10 and all(c["water_regime"] is None for c in cs)
    wheat = [c for c in cs if c["crop"] == "Wheat"]
    assert [(c["start_month"], c["start_week"], c["end_month"], c["end_week"]) for c in wheat] == [(11, 2, 12, 2)]


def test_sangli_two_sugarcane_windows():
    cs = [c for c in pick("Maharashtra/Sangli", claim_type="sowing_window") if "Sugarcane" in c["crop"]]
    got = {(c["crop"], c["start_month"], c["end_month"]) for c in cs}
    assert ("Sugarcane (Seasonal)", 1, 1) in got and ("Sugarcane (Pre seasonal)", 10, 11) in got


def test_normal_onset_row_is_a_dry_spell():  # Tumkur p12
    cs = [c for c in claims("Karnataka/Tumkur") if c["page"] == 12 and "Normal onset" in c["statement"]]
    assert cs and all(c["condition"] == "early_dry_spell" for c in cs)
    assert not [c for c in cs if c["claim_type"] == "contingency_crop_change" and "Cowpea" in c["recommended_crops"]]


def test_measures_drop_list_numbers():
    assert rules.measures_of("1.Repeated weeding 2.Removal of weaklings 3.Spray 2.0 % urea") == \
        ["Repeated weeding", "Removal of weaklings", "Spray 2.0 % urea"]
