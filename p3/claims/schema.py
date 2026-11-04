"""Claim format for the Claim Extractor (Person 3).

`Claim` is what the LLM returns for one page (also used as the Gemini response
schema). `StoredClaim` is what we write to claims/<State>/<District>.jsonl after all
checks pass. The format is provisional; change it here and nowhere else.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "0.1"


class ClaimType(str, Enum):
    rainfall_normal = "rainfall_normal"          # 1.2 normal rainfall / rainy days per season
    monsoon_onset = "monsoon_onset"              # 1.2 normal onset week
    monsoon_cessation = "monsoon_cessation"      # 1.2 normal cessation week
    crop_area = "crop_area"                      # 1.7 area under a crop
    crop_production = "crop_production"          # 1.11 production / productivity
    sowing_window = "sowing_window"              # 1.12 normal sowing period
    hazard_proneness = "hazard_proneness"        # 1.13 drought/flood/... regular/occasional/none
    contingency_crop_change = "contingency_crop_change"  # 2.x crop to grow under a condition
    contingency_measure = "contingency_measure"  # 2.x agronomic / management measures


class Season(str, Enum):
    sw_monsoon = "sw_monsoon"
    ne_monsoon = "ne_monsoon"
    winter = "winter"
    summer = "summer"
    annual = "annual"
    kharif = "kharif"
    rabi = "rabi"


class Metric(str, Enum):
    rainfall_mm = "rainfall_mm"
    rainy_days = "rainy_days"
    area_000ha = "area_000ha"
    production_000t = "production_000t"
    productivity_kg_ha = "productivity_kg_ha"


class WaterRegime(str, Enum):
    rainfed = "rainfed"
    irrigated = "irrigated"


class Hazard(str, Enum):
    drought = "drought"
    flood = "flood"
    cyclone = "cyclone"
    hailstorm = "hailstorm"
    heat_wave = "heat_wave"
    cold_wave = "cold_wave"
    frost = "frost"
    sea_water_intrusion = "sea_water_intrusion"
    pests_diseases = "pests_diseases"
    other = "other"


class Frequency(str, Enum):
    regular = "regular"
    occasional = "occasional"
    none = "none"


class Condition(str, Enum):
    delayed_onset = "delayed_onset"                  # monsoon delayed by N weeks
    early_dry_spell = "early_dry_spell"              # normal onset then 15-20 day dry spell
    mid_season_drought_vegetative = "mid_season_drought_vegetative"
    mid_season_drought_flowering = "mid_season_drought_flowering"
    terminal_drought = "terminal_drought"
    unusual_rain = "unusual_rain"                    # continuous high rain, waterlogging
    flood = "flood"
    heat_wave = "heat_wave"
    cold_wave = "cold_wave"
    frost = "frost"
    hailstorm = "hailstorm"
    cyclone = "cyclone"
    other = "other"


class Claim(BaseModel):
    """One small, testable statement from one page. Fields not used by the type stay null."""
    claim_type: ClaimType
    statement: str = Field(description="The claim as one plain English sentence, e.g. "
                           "'Normal SW monsoon (June-Sep) rainfall is 3273 mm.'")
    quote_parts: List[str] = Field(description="1-6 fragments copied character for character "
                                   "from the CURRENT page that together support the claim "
                                   "(table cells may be separate fragments).")
    season: Optional[Season] = None
    water_regime: Optional[WaterRegime] = None
    crop: Optional[str] = Field(None, description="Crop as written in the plan, e.g. 'Paddy'.")
    metric: Optional[Metric] = None
    value: Optional[float] = None
    ref_year: Optional[str] = Field(None, description="Data year the plan gives, e.g. '2008-09'.")
    start_month: Optional[int] = Field(None, description="1-12")
    start_week: Optional[int] = Field(None, description="Week of month, 1-5")
    end_month: Optional[int] = None
    end_week: Optional[int] = None
    hazard: Optional[Hazard] = None
    frequency: Optional[Frequency] = None
    condition: Optional[Condition] = None
    delay_weeks: Optional[int] = None
    dry_spell_min_days: Optional[int] = None
    dry_spell_max_days: Optional[int] = None
    crop_stage: Optional[str] = None
    farming_situation: Optional[str] = None
    normal_crop: Optional[str] = None
    recommended_crops: List[str] = Field(default_factory=list,
                                         description="Crops to grow instead; ['No change'] allowed")
    measures: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _required_fields(self):
        missing = [f for f in REQUIRED[self.claim_type] if getattr(self, f) in (None, [], "")]
        if missing:
            raise ValueError(f"{self.claim_type.value} needs {', '.join(missing)}")
        if not 1 <= len(self.quote_parts) <= 6:
            raise ValueError("quote_parts must have 1-6 fragments")
        for m in ("start_month", "end_month"):
            v = getattr(self, m)
            if v is not None and not 1 <= v <= 12:
                raise ValueError(f"{m} must be 1-12")
        for w in ("start_week", "end_week"):
            v = getattr(self, w)
            if v is not None and not 1 <= v <= 5:
                raise ValueError(f"{w} must be 1-5")
        return self


REQUIRED = {
    ClaimType.rainfall_normal: ["season", "metric", "value"],
    ClaimType.monsoon_onset: ["season", "start_month", "start_week"],
    ClaimType.monsoon_cessation: ["season", "start_month", "start_week"],
    ClaimType.crop_area: ["crop", "metric", "value"],
    ClaimType.crop_production: ["crop", "metric", "value"],
    ClaimType.sowing_window: ["crop", "start_month", "end_month"],
    ClaimType.hazard_proneness: ["hazard", "frequency"],
    ClaimType.contingency_crop_change: ["condition", "normal_crop", "recommended_crops"],
    ClaimType.contingency_measure: ["condition", "measures"],
}


class PageClaims(BaseModel):
    claims: List[Claim]


class StoredClaim(Claim):
    claim_id: str            # "<plan_id>#p<page>#c<n>"
    plan_id: str             # "Karnataka/Udupi"
    state: str
    district: str
    census_code_2011: Optional[str] = None
    page: int                # 1-based PDF page
    quote_match: str         # "exact" or "loose" (matched after removing all whitespace)
    model: str
    prompt_version: str
    schema_version: str = SCHEMA_VERSION
