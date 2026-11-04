# Person 3 work log — Monsoon Plan Checker

Everything done on P3's part (claims, plan figures, planted claims, report Intro/Related work).
**Rule: every future change is appended here (newest at the bottom), with date, what, why, result.**

Project: check 105 ICAR-CRIDA District Agriculture Contingency Plans (KA 29, MH 34, RJ 33, TG 9)
against IMD rainfall and crop data with tool-using LLM agents. P3 owns: page text, Claim Extractor,
plan figures, planted claims, crop names (with P2), report Intro + Related work.

---

## Up to 4 Nov 2026 (before this log)
- **Task 1** `p3/extract_text.py` → `plan_text/` (105 plans, 3,321 pages, PyMuPDF; no OCR needed).
- **Task 7** draft `p3/report/intro_related.tex` + `refs.bib` (IEEEtran).
- **Task 2** Gemini extractor built (`p3/claims/extract.py`, `gemini.py`, `prompt.py`, `schema.py`,
  `checks.py`). Free Gemini = 20 requests/day; flash-lite skips table rows; Groq ~200k tokens/day —
  too small for 105 plans (~2,300 page calls). Declined rotating several Google accounts (ToS).
  → **Switched to the rule-based extractor `p3/claims/rules.py`** (no API calls). Gemini kept for a
  small comparison sample only.
- Built `claims_rules/`, `planted_text/` + `answers.csv`, `plan_figures.csv`, `crop_names.csv`,
  `review/claim_review.xlsx` (30 plans, 300 claims + 30 pages).

## 4 Nov 2026 — first review (marked by Claude, AI)
- `review/claim_review.xlsx` scored the OLD extractor: precision 274/300 = 91.3%, recall 69.9%.
- Bugs found: dropped crops in recommendations ("Fallow-mustard" → "Fallow"), merged table cells
  only on first row, irrigated (2.1.2) rows called "Terminal drought", paired kharif/rabi rows,
  wrong units ('00 MT), month-only sowing windows, split rows, truncation.

## 4 Nov 2026 — fixes round 1 (all bugs from the first review)
- `plan_text/` now has `table_merges` (merged-cell map; `tables` unchanged); `rules.filled_tables()`.
- Crop-change statements quote the plan cell verbatim; `recommended_crops` lists every crop
  (`crops.crop_mentions`). Parsing stops at the 2.1.2 heading. Paired rows split per crop.
  Non-'000 t production skipped. Year-rainfall column handled. Page-break rows joined.
- Found & fixed extra: "Kharif" rows as crops, Hassan "Kharif (June-Sep)" rainfall, "(Kharif)" as
  crop, `planted.py` en-dash bug (planted text and tables were inconsistent).
- Tests: `p3/tests/test_review_fixes.py` (one test per bug).

## 4 Nov 2026 — pilot switched + pilot audit
- Pilot = P1's DB districts: Chamarajanagar, Chitradurga, Kalaburagi (=plan Gulbarga),
  Shivamogga (=Shimoga), Tumakuru (=Tumkur) in `p3/claims/extract.py`.
  **Open question for P1:** Census-2011 Gulbarga includes Yadgir (separate plan) — which boundary?
- Fixed: symbol-font ticks (\x01, ) → +133 hazard claims; split Total irrigated/rainfed area
  (`crop_area_part` in plan_figures.csv, never ranked); rainfall cell window (cessation);
  onset/cessation by position; Roman fortnights; no half-range guessing (~40 wrong old windows);
  condition carry-over on repeated headers; continued hazard/production/area tables;
  leading-zero numbers ("0640") skipped.

## 4 Nov 2026 — held-out review (THE numbers for the paper)
- `review/heldout_plans.txt`: the 30 plans never used for fixing (MH 15, RJ 10, KA 4, TG 1 —
  uneven, say so). Sheet `review/claim_review_v2.xlsx`, marked by Claude (AI), extractor frozen
  before marking. **Precision 279/300 = 93.0%, recall 392/437 = 89.7%.**
  Re-show: `python -m p3.review --score --out review/claim_review_v2.xlsx`.
- Bugs it found (fixed after scoring): "(July 2nd wk)" / "11th-20th June" / "Delay by 8 week Aug
  2nd week" dates (~490 claims), Grand-total area columns ignored (e.g. Jaipur pearl millet 0 →
  295.7), rabi sowing sub-headers / in-cell crop names / "(Guar/ Gram)" headers (~70 windows),
  "Avoid X" crops listed as recommended (112 claims), "No change / alternative", "(ha)" sections
  read as '000 ha, Sangli shifted Total columns, "Rabi crop planting" column, horticulture
  sub-tables, fodder crops, Azwain/Cumin/Isabgol, mid-season rows with no stage (now skipped).

## 4 Nov 2026 — rejected claims recovered
- Subscript digits in table cells ("KNO /K SO … 3 2 4") made quotes fail. `rules.page_span` /
  `repair_quotes` now use the page's own text (digits in place). Rejected 149 → 25; +110 claims.

## 4 Nov 2026 — report (Task 7)
- `refs.bib`: URLs added — PIB 23 Jun 2026 (PRID 2277178), IWMI SukhaRakshak blog (Jul 2025).
- `intro_related.tex`: extractor now described as deterministic; contribution 1 has ~16,500
  claims, held-out 93.0% / 89.7% (AI-assisted labels), 683 planted errors; FActScore line fixed.
  Static check: all \cite keys present, braces balanced (no LaTeX installed locally).
  TODOs in the file: P5's headline result; wording after human spot-check.
- Noted earlier as "14 states / 342 districts" — corrected below after reading the source.

## 4 Nov 2026 — Parliament fact verified and added to the Introduction
- Source read: Lok Sabha Unstarred Q 3886, 11 Aug 2026 (MoS Ramnath Thakur), sansad.in PDF:
  DACPs "updated for 15 States including Maharashtra covering 342 Districts which are likely to
  receive below normal rainfall by ... ICAR-CRIDA"; "available at the District-level and not
  maintained centrally". (15 states, not 14; "14" was a count of ICAR-CRIDA state meetings.)
- intro_related.tex: one sentence added after the PIB sentence; refs.bib: `loksabha2026dacp`.
  Static check passes.
- User: will push all files to GitHub for teammates and relay P1/P2/P4/P5 answers later.

## 4 Nov 2026 — spot-check sheet for the user
- `review/spotcheck.xlsx`: 30 rows from claim_review_v2.xlsx (seed 2026: 24 marked Y + 6 marked N,
  shuffled), with PDF links. User fills column J (agree Y/N) + K (note). Then Claude counts
  agreement and updates the Intro wording ("checked by hand on a sample").

## 4 Nov 2026 — Gemini vs rules comparison (IN PROGRESS)
- `p3/compare_llm.py` → `review/llm_comparison.csv` (9 held-out pages). Quota ran out after 8 pages
  (429, resets ~21 h). Script crashed before writing the CSV; answers are cached in
  `claims/_cache`, so re-running tomorrow costs only the missing pages.
- Partial (rules / Gemini accepted claims): Kolar p1 9/9, Nashik p3 15/32, Barmer p4 16/8,
  Belgaum p5 48/51, Thane p7 9/9, Buldhana p12 12/12, Nanded p10 18/0, Jaipur p14 15/3,
  Sindhudurg p19 not run. Field-by-field agreement not yet computed.
- **Next:** re-run `python -m p3.compare_llm` after the quota resets; fill in the table; add one
  sentence/table to the paper.

## Current state (4 Nov 2026, end of session)
- `claims_rules/` 16,514 claims, 25 rejected; 36 tests pass (`python -m pytest p3/tests`).
- Planted: 683 errors, all re-extracted (rebuilt after the rejected-claims recovery);
  plan_figures.csv and crop_names.csv (1,222 names) rebuilt too.
- Rebuild everything: `python -m p3.claims.rules --all && python -m p3.planted --all &&
  python -m p3.claims.rules --planted --all && python -m p3.planted --verify &&
  python -m p3.figures && python -m p3.crops`

## Remaining
- **User:** send updated files to teammates
  (claims_rules/, planted_text/+answers.csv, claims_rules_planted/, plan_figures.csv,
  crop_names.csv, plan_text/); ask P1 (Kalaburagi boundary); 8 questions to P4/P5; P2 to check
  crop_names.csv.
- **Claude:** finish Gemini comparison (after quota reset); rebuild downstream; add P5 result to
  Intro when frozen; compile check in Overleaf / Word if needed.
- Known gaps (stated, not hidden): plan-side unit errors (e.g. Haveri mango in ha labelled
  '000 ha); no-unit vegetable sub-tables skipped; 2.1.2 irrigated and 2.2+ sections not parsed.

## 4 Nov 2026 — spot-check done (AI-assisted, not by hand)
- User could not do the hand check; Claude re-checked all 30 rows of `review/spotcheck.xlsx`
  against plan_text and rendered PDF page images (tick-mark tables, merged cells, delay headers
  on earlier pages). Agreed with all 30 marks (24 Y, 6 N). Column J/K filled, header says
  "AI-assisted second check".
- Caveat: for the 6 N rows the old (pre-fix) parsed week isn't stored anymore; checked that the
  plan's text gives the value in the note, and the bug is the one logged above.
- Paper wording unchanged: stays "labelled with AI assistance" (user's decision). TODO removed
  from intro_related.tex.

## 4 Nov 2026 — teammate answers (relayed by user)
- P1: Census 2011 shapefile has Gulbarga and Yadgir as separate features; only Gulbarga mapped
  to Kalaburagi. So the P1 database is fine.
- But the Gulbarga plan (KA8, 3 Feb 2011) describes the UNDIVIDED district: its geographical area
  is 1610.2 ('000 ha, mislabelled "Lakh ha"). The Yadgir plan gives 516. Post-split Gulbarga is
  about 1,092, and 1,092 + 516 ≈ 1,610. Gulbarga plan area/production figures therefore cover
  Gulbarga + Yadgir. Area/production checks for Kalaburagi should use Gulbarga+Yadgir crop data
  or skip it. Rainfall normals are less affected. Told the user to pass this to P2/P5.
- Teammate suggestions: same LLM for baseline and agents; freeze a stratified ~300-claim eval
  set that all three systems use; they will review p3/claims/schema.py; LaTeX/Overleaf IEEE
  (matches intro_related.tex, so the Word conversion is not needed); use DVC for data versions.
- Still waiting: P4's provider, model and limits.

## 4 Nov 2026 — .gitignore for GitHub push
- `.gitignore` now excludes: .env (Gemini key), IMD rainfall NetCDF (data/imd, 1.1 GB),
  IMD temperature GRD (data/imd_temp, 121 MB), crops CSV (data/crops, 54 MB), caches, Office
  lock files. These three data folders go to teammates via Google Drive.
- What gets pushed is about 113 MB; the largest file is under 10 MB (2011_Dist.shp, 9.8 MB).
  No API keys found in code.
- Pushed 4 Nov: git repo created, commit d40c0a7 (786 files) pushed to
  https://github.com/igris-57/SEM-5-EL.git, branch main. Verified .env and the 3 data folders
  are not tracked.
- Same day: faculty rule "no datasets in the repo". Rewrote the single commit without data and
  force-pushed. Repo now has code, report, docs, download scripts + links CSV only. Data
  (raw + p3 outputs + review xlsx) shared via Google Drive at the same paths; see .gitignore.
