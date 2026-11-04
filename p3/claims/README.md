# Claim Extractor (Person 3)

Turns `plan_text/` into small testable claims. Two extractors share one schema and the
same checks:

- **`rules.py` (main):** a deterministic parser for the CRIDA template tables. It needs no LLM
  and covers all 105 plans → **`claims_rules/`** (about 11.7k claims). Use these claims.
- **`extract.py` (comparison):** one Gemini call per page → `claims/`. Free-tier limits
  (20 requests/day on gemini-3.5-flash) mean it only runs on samples, to compare against the rules.

```
pip install pymupdf pydantic pandas openpyxl google-genai pytest
python p3/extract_text.py                    # plan_text/ (page text + rebuilt tables)
python -m p3.claims.rules --all              # claims_rules/   (main claims)
python -m p3.planted --pilot                 # planted_text/ + answers.csv (check 2)
python -m p3.claims.rules --planted --all    # claims_rules_planted/
python -m p3.planted --verify                # answers.csv: extracted=yes/no per planted error
python -m p3.figures                         # plan_figures.csv (check 1)
python -m p3.crops                           # crop_names.csv (with Person 2)
python -m p3.review                          # review/claim_review.xlsx (hand labels)
python -m pytest p3/tests                    # offline tests
```

The rule parser reads sections 1.2, 1.7, 1.11, 1.12, 1.13 and the 2.1 rainfed drought
tables (delayed onset, early dry spell, mid-season, terminal). It does not yet read 2.1.2
(irrigated), 2.2–2.4 (unusual rain, floods, extreme events) or the livestock tables.
In some plans the 1.13 hazard ticks are images, so those plans have no hazard claims.

How the parser handles the template's quirks (each has a test in `p3/tests/test_review_fixes.py`):
- A merged cell (one "No change" spanning five crop rows) applies to every row it covers.
- A row split by a page break is joined; each half is quoted separately.
- Parsing stops at the 2.1.2 (irrigated) heading, so canal / groundwater rows are never
  labelled as rainfed drought.
- Crop-change claims quote the plan's cell word for word; `recommended_crops` lists every crop
  named in it, as written ("Fallow-mustard" -> `["Fallow", "mustard"]`). Only delayed-onset
  tables give crop changes; in the other tables that column is read as measures.
- Rows that pair a kharif and a rabi crop ("Guar/Gram", "Bajra | ... | 464.033 Wheat | 3422")
  give each crop its own values; totals over two crops are skipped.
- Production not given in '000 t (tonnes, '00 MT, quintals) is skipped; productivity is kept.
- Plans that add a one-year rainfall column ("RF(mm) 2009") take rainy days from the right column.
- Tables that run on to the next page (area, production, hazard ticks, drought blocks) keep their
  headings and condition, with or without a repeated header.
- Dates: Roman fortnights ("June IInd FN"), "July end", bare months ("June to August") are read;
  a range with one unreadable side, or an end without a month before its start, gives no claim.
- Ticks drawn in a symbol font are read; ambiguous numbers like "0640" are skipped.

## Output (`claims_rules/`, same format in `claims/`)
- `<State>/<District>.jsonl`: accepted claims, one JSON object per line (`StoredClaim` in `schema.py`)
- `_rejected/<State>/<District>.jsonl`: claims that failed a check, with the reasons
- `run_log.csv`: one row per page (claims, rejects, retry, tokens, seconds, cached)
- `_cache/`: raw Gemini answers, so re-runs are free

## Claim format (provisional, `SCHEMA_VERSION` 0.1)
Every claim has `claim_id` (`<plan_id>#p<page>#c<n>`), `plan_id`, `census_code_2011`, `page`,
`claim_type`, `statement` (one English sentence), `quote_parts` (verbatim fragments from that page)
and `quote_match` (`exact`/`loose`). Type-specific fields:

| claim_type | Plan section | Key fields |
|---|---|---|
| `rainfall_normal` | 1.2 | `season`, `metric` (rainfall_mm / rainy_days), `value` |
| `monsoon_onset`, `monsoon_cessation` | 1.2 | `season`, `start_month`, `start_week` |
| `crop_area` | 1.7 | `crop`, `season`, `water_regime`, `metric`=area_000ha, `value`, `ref_year` |
| `crop_production` | 1.11 | `crop`, `season`, `metric` (production_000t / productivity_kg_ha), `value` |
| `sowing_window` | 1.12 | `crop`, `season`, `water_regime`, `start_month/week`, `end_month/week` |
| `hazard_proneness` | 1.13 | `hazard`, `frequency` (regular / occasional / none) |
| `contingency_crop_change` | 2.x | `condition`, `delay_weeks` or `dry_spell_min/max_days`, `farming_situation`, `normal_crop`, `recommended_crops` |
| `contingency_measure` | 2.x | `condition`, `normal_crop`, `measures` |

Weeks are week-of-month (1–5), so "3rd week of June" means `start_month=6, start_week=3`.

## Checks before a claim is kept
1. Pydantic: valid enums, and the fields required for its `claim_type`.
2. Quote check: every `quote_parts` fragment appears on that page, either word for word
   after collapsing whitespace (`exact`), or after removing all whitespace (`loose`),
   which handles PDF splits like "t o".
3. Number check: every number in the fields (value, weeks, days) appears in the quote, and
   every month set is named in it.

A page that fails any check gets one retry with the problems listed. Whatever still fails
goes to `_rejected/`.
