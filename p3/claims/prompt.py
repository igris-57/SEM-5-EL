"""Prompt for the per-page Claim Extractor call. Bump PROMPT_VERSION on every change."""

PROMPT_VERSION = "p3-extract-v2"  # v2: rebuilt tables added to the prompt

SYSTEM = """\
You extract testable claims from one page of an Indian District Agriculture Contingency
Plan (ICAR-CRIDA template). The page text came from a PDF: table cells appear one per
line, so rebuild table rows yourself before reading them.

Return every claim of these types found on the CURRENT PAGE, one fact per claim:
- rainfall_normal: normal rainfall (metric rainfall_mm) or normal rainy days (metric
  rainy_days) for a season (sw_monsoon, ne_monsoon, winter, summer, annual). One claim per
  season and metric.
- monsoon_onset / monsoon_cessation: normal onset or cessation week of a season.
  start_month (1-12) and start_week (1-5) give the week.
- crop_area: area under one crop (metric area_000ha, in '000 ha), with season and
  water_regime if the table gives them, and ref_year if stated (e.g. "2008-09").
  Only field, horticulture and plantation crops; skip fodder/grazing/livestock.
- crop_production: production (production_000t) or productivity (productivity_kg_ha)
  of one crop in one season. One claim per number.
- sowing_window: normal sowing period of a crop: season, water_regime, start_month/
  start_week to end_month/end_week.
- hazard_proneness: a hazard (drought, flood, cyclone, hailstorm, heat_wave, cold_wave,
  frost, sea_water_intrusion, pests_diseases, other) ticked as regular, occasional or none.
- contingency_crop_change: under a condition, the crop(s) to grow instead of the normal
  crop. Use recommended_crops=["No change"] when the plan says no change.
- contingency_measure: under a condition, the agronomic / management measures for the
  normal crop (list them in measures, as short phrases from the page).

For contingency claims set condition to one of: delayed_onset (set delay_weeks, and the
expected sowing week as start_month/start_week if given), early_dry_spell (normal onset
then a dry spell; set dry_spell_min_days/max_days e.g. 15 and 20),
mid_season_drought_vegetative, mid_season_drought_flowering, terminal_drought,
unusual_rain, flood, heat_wave, cold_wave, frost, hailstorm, cyclone, other. Also set
farming_situation and normal_crop as written. Make one claim per (condition, farming
situation, normal crop).

Rules:
1. quote_parts are 1-6 fragments copied CHARACTER FOR CHARACTER from the CURRENT PAGE
   (keep the page's spelling, spacing and typos). Use separate fragments for separate
   table cells. Never quote the previous-page context.
2. Every number you put in a field (value, weeks, days) must appear in quote_parts, and
   every month you set must be named in quote_parts.
3. Do not infer, convert units or fill in missing values. If a table cell is "-" or
   empty, there is no claim.
4. Skip addresses, coordinates, soils, land use, irrigation sources, livestock,
   fisheries, maps and headings with no fact.
5. If the page has no claims, return {"claims": []}.
"""


def page_prompt(plan, page, prev_text):
    prev = prev_text[-1500:] if prev_text else "(none)"
    tables = "\n\n".join(page.get("tables") or []) or "(none detected)"
    return (
        f"District: {plan['district']}, {plan['state']}\n"
        f"Page: {page['page']} of {plan['n_pages']}\n\n"
        f"--- END OF PREVIOUS PAGE (context only, do not quote) ---\n{prev}\n\n"
        f"--- TABLES ON THE CURRENT PAGE (rows rebuilt from the PDF; use them to read "
        f"which cells belong together, one claim per row and column) ---\n{tables}\n\n"
        f"--- CURRENT PAGE TEXT (copy quote_parts from here) ---\n{page['text']}\n"
    )


def retry_prompt(base, problems):
    issues = "\n".join(f"- {p}" for p in problems)
    return (base + "\n--- YOUR PREVIOUS ANSWER HAD THESE PROBLEMS ---\n" + issues +
            "\nReturn the full corrected list of claims for the current page. Drop any "
            "claim you cannot support with exact quotes.\n")
