# Person 3: status and hand-over (8 Nov 2026)

Person 3 owns the claim extractor, the plan figures and the planted claims (work split p.3),
plus the report's Introduction and Related Work. Full history: `p3/WORKLOG.md`.

## Done

| Task (work split) | Result | Where |
|---|---|---|
| Page text for all 105 plans | 3,321 pages, PyMuPDF, no OCR needed | `plan_text/` (Drive) |
| Claim extractor + format check + exact-quote check | Rule-based parser over the plan tables: 16,514 claims, each with page and word-for-word quote | `p3/claims/rules.py` → `claims_rules/` (Drive) |
| Pilot review, then spot-check | 30 held-out plans, 300 claims: precision 93.0%, recall 89.7%. Labels made with AI assistance, not by hand | `review/claim_review_v2.xlsx` (Drive) |
| Plan figures | Every number a plan states about its district | `plan_figures.csv` (Drive) |
| Planted claims for all 105 | 683 planted errors with answer key; all 683 re-extracted from the planted copies | `planted_text/`, `claims_rules_planted/` (Drive) |
| crop_names.csv | 1,222 plan crop names mapped to crop-data names | `crop_names.csv` (Drive) |
| Report: Introduction and Related Work | LaTeX, IEEE template | `p3/report/` |
| LLM comparison | 9 held-out pages, rules vs Gemini 3.5 Flash (free tier) | `p3/compare_llm.py` → `review/llm_comparison.csv` |
| Hand-off to P4/P5 | Claims per district code with decision-rule tags, answer key with claim ids, draft 300-claim evaluation set | `p3/export.py`, `p3/evalset.py` → `data/processed/` (Drive) |

Tests: `python -m pytest p3/tests` (41 pass).

## What was planned but done differently

**The extractor does not use an LLM.** The work split planned one LLM call per page. That code
exists (`p3/claims/gemini.py`, `prompt.py`, `extract.py`) but was not used for the dataset:

- Free Gemini allowed about 20 requests a day; 3,321 pages would take about 166 days.
- The free lighter model skipped table rows. On the 9-page comparison, Gemini gave the same values
  as the rules wherever both found a fact, but returned only 3 of 33 rows on two drought tables
  and left the dates empty on a third page.
- No paid API was available to Person 3.

The rule-based parser is free, copies quotes exactly and cannot invent numbers. The paper says so.

**Spot-check labels are AI-assisted, not by hand.** The paper says "labelled with AI assistance".

## Not done

| Item | Why | Who / what is needed |
|---|---|---|
| LLM extraction of all plans | No free LLM with enough capacity | Someone with a GPU (Ollama, ~7B model) or a paid API. `extract.py` would need an Ollama client next to `gemini.py`; the checks and quote matching can be reused. Optional: the rule-based claims are complete without it |
| Sections 2.1.2 (irrigated) and 2.2 onward | Time | Parse the same way as 2.1.1 in `rules.py`. Mostly measures, which have no decision rule yet |
| Units the plans themselves get wrong (e.g. Haveri mango in ha labelled '000 ha), vegetable tables without units | Plan-side errors | Stated as limitations |
| crop_names.csv checked by Person 2 | Waiting on P2 | P2 |
| Fixes from Person 5's check 1 | No problems reported yet | P5 |
| Headline result in the Introduction | Waiting on P5's final numbers | P5, then one sentence in `p3/report/intro_related.tex` |
| Final evaluation set | Team must agree on the mix and the decision-rule questions | All; see `data/processed/README.md` |

## Questions raised for the team

See `data/processed/README.md`: 11,821 claims have no decision rule; the rainfall and onset rules
ignore the plan's own number, so 288 planted errors cannot be caught; the sowing rule does not
fit rabi windows; Gulbarga's plan covers Gulbarga + Yadgir; Palghar repeats Thane.

## Rebuild everything

```
python -m p3.claims.rules --all && python -m p3.planted --all && python -m p3.claims.rules --planted --all
python -m p3.planted --verify && python -m p3.figures && python -m p3.crops
python -m p3.export --all && python -m p3.evalset
```
