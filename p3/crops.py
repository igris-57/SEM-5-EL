"""Crop names (plan spelling -> crop-data name) and which crops each plan district grows.

    python -m p3.crops        # writes crop_names.csv from all claims found so far

crop_names.csv is shared with Person 2: the `crop_data_name` column must be a crop_name
that exists in the district crop CSV. Rows with match=none need a decision.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "DOCS" / "data" / "Main EL" / "data"
CROPS_CSV = DATA / "crops" / "crop-wise-area-production-yield.csv"
CROSSWALK = DATA / "district_crosswalk.csv"
CLAIM_DIRS = [ROOT / "claims_rules"]
OUT = ROOT / "crop_names.csv"

# plan spellings -> crop_name in the crop CSV. Keys are matched after key() normalisation.
ALIASES = {
    "Rice": ["paddy", "rice", "kharif paddy", "rabi paddy", "summer paddy", "transplanted paddy",
             "direct seeded paddy", "upland paddy", "lowland paddy", "basmati"],
    "Jowar": ["jowar", "sorghum", "kharif jowar", "rabi jowar", "fodder jowar", "jawar", "jowari"],
    "Bajra": ["bajra", "pearl millet", "pearlmillet", "sajje", "bajara"],
    "Ragi": ["ragi", "finger millet", "fingermillet", "nachni", "nagli"],
    "Maize": ["maize", "corn", "kharif maize", "rabi maize", "hybrid maize", "makka"],
    "Wheat": ["wheat", "durum wheat"],
    "Barley": ["barley", "jau"],
    "Small Millets": ["small millets", "minor millets", "little millet", "kodo millet", "kodo",
                      "proso millet", "barnyard millet", "sawa"],
    "Korra": ["korra", "foxtail millet", "navane", "kangni", "setaria"],
    "Samai": ["samai", "sama"],
    "Varagu": ["varagu"],
    "Arhar/Tur": ["redgram", "red gram", "tur", "tuar", "arhar", "pigeonpea", "pigeon pea", "tur dal",
                  "togari"],
    "Moong(Green Gram)": ["greengram", "green gram", "moong", "mung", "mungbean", "mung bean",
                          "summer moong", "summer greengram", "moongbean", "moong bean",
                          "mungbeans"],
    "Urad": ["blackgram", "black gram", "urad", "urd", "black gram urad", "urdbean", "urd bean",
             "urid", "uradbean"],
    "Gram": ["bengalgram", "bengal gram", "chickpea", "chick pea", "gram", "chana", "kabuli chana"],
    "Horse-Gram": ["horsegram", "horse gram", "kulthi", "hurali"],
    "Cowpea(Lobia)": ["cowpea", "cow pea", "lobia", "chawli", "alasande",
                      "cowpe"],  # Tumkur plan typo 'CowpeC-152)'
    "Masoor": ["lentil", "masoor", "masur"],
    "Moth": ["moth", "mothbean", "moth bean", "matki"],
    "Peas & Beans (Pulses)": ["field bean", "fieldbean", "dolichos", "avare", "peas", "pea",
                              "rajmash", "rajma", "french bean"],
    "Groundnut": ["groundnut", "ground nut", "peanut", "kharif groundnut", "rabi groundnut",
                  "summer groundnut"],
    "Soyabean": ["soybean", "soyabean", "soya bean", "soy bean"],
    "Sunflower": ["sunflower", "sun flower"],
    "Safflower": ["safflower", "kardai"],
    "Sesamum": ["sesamum", "sesame", "til", "gingelly", "seasamum"],
    "Niger Seed": ["niger", "nigerseed", "niger seed", "ramtil", "khurasani"],
    "Castor Seed": ["castor", "castor seed"],
    "Linseed": ["linseed", "flax", "alsi"],
    "Rapeseed &Mustard": ["mustard", "rapeseed", "rapeseed mustard", "rape seed and mustard",
                          "rapeseed and mustard", "taramira", "toria", "sarson", "rai"],
    "Cotton(Lint)": ["cotton", "bt cotton", "desi cotton", "hybrid cotton", "american cotton",
                     "rainfed cotton", "irrigated cotton"],
    "Sugarcane": ["sugarcane", "sugar cane"],
    "Guar Seed": ["guar", "clusterbean", "cluster bean", "guar seed"],
    "Mesta": ["mesta"],
    "Sannhamp": ["sunhemp", "sunnhemp", "sannhamp", "sun hemp"],
    "Tobacco": ["tobacco"],
    "Dry Chillies": ["chilli", "chillies", "chilly", "chillis", "dry chilli", "dry chillies",
                     "red chilli", "chili"],
    "Turmeric": ["turmeric"],
    "Ginger": ["ginger"],
    "Coriander": ["coriander", "dhania"],
    "Garlic": ["garlic"],
    "Onion": ["onion", "kharif onion", "rabi onion"],
    "Potato": ["potato"],
    "Sweet Potato": ["sweet potato", "sweetpotato"],
    "Tapioca": ["tapioca", "cassava"],
    "Tomato": ["tomato"],
    "Brinjal": ["brinjal", "eggplant", "baingan"],
    "Bhindi": ["bhindi", "okra", "lady finger", "ladys finger", "bhendi"],
    "Cabbage": ["cabbage"],
    "Cucumber": ["cucumber"],
    "Bottle Gourd": ["bottle gourd", "bottlegourd"],
    "Peas (Vegetable)": ["green peas", "vegetable peas"],
    "Other Vegetables": ["vegetables", "vegetable", "vegitables", "leafy vegetables",
                         "cauliflower", "carrot", "coccinia", "ash gourd", "bitter gourd",
                         "ridge gourd", "cluster bean vegetable", "radish", "beans"],
    "Other Fresh Fruits": ["guava", "ber", "aonla", "custard apple", "fig", "jackfruit", "jack fruit"],
    "Banana": ["banana"],
    "Mango": ["mango"],
    "Grapes": ["grapes", "grape"],
    "Papaya": ["papaya"],
    "Sapota": ["sapota", "chiku", "chikoo"],
    "Pome Granet": ["pomegranate", "pomegranet", "pome granate"],
    "Citrus Fruit": ["citrus", "sweet orange", "mosambi", "mosambi sweet orange"],
    "Orange": ["orange", "nagpur orange", "mandarin"],
    "Lemon": ["lemon", "lime", "acid lime"],
    "Water Melon": ["watermelon", "water melon"],
    "Coconut": ["coconut"],
    "Arecanut": ["arecanut", "areca nut", "areca", "supari"],
    "Cashewnut": ["cashew", "cashewnut", "cashew nut"],
    "Black Pepper": ["pepper", "black pepper"],
    "Cardamom": ["cardamom"],
}


# spellings seen in the plans' contingency tables
TYPOS = {"Guar Seed": ["custerbean", "custer bean"], "Moong(Green Gram)": ["greengra"],
         "Urad": ["blackgraim"], "Peas & Beans (Pulses)": ["field beanl"], "Soyabean": ["soya"]}
for _crop, _names in TYPOS.items():
    ALIASES[_crop] = ALIASES[_crop] + _names
# crops / land uses with no crop-data row that the contingency tables still plan for
NON_CSV_CROPS = re.compile(r"henna|mehandi|mahandi|napier|lucerne|pasture|grass|green manur|"
                           r"pulses|fodder|silvi|vegetable", re.I)


def key(name):
    return re.sub(r"[^a-z]", "", name.lower())


ALIAS_INDEX = {key(a): crop for crop, names in ALIASES.items() for a in names + [crop]}


SEASON_WORDS = re.compile(r"^\s*(kharif|rabi|summer|late|early|irrigated|rainfed|sole|hybrid|"
                          r"local|desi|improved)\s+", re.I)


def to_crop_data_name(plan_name):
    """Crop-data name for a plan crop string, or None. Tries the whole string, then the part
    before '(' '+' '/' ':' '-' '–' (e.g. 'Paddy (Kharif)', 'Paddy – Pulses' -> first crop),
    each also without a leading season word ('Rabi sorghum' -> Jowar)."""
    if not plan_name:
        return None
    first = re.split(r"[(\[+/,:;\-–—]|\s\bor\b\s|\s\band\b\s", plan_name)[0]
    for cand in (plan_name, first):
        for c in (cand, SEASON_WORDS.sub("", cand)):
            hit = ALIAS_INDEX.get(key(c))
            if hit:
                return hit
    return None


# crops the contingency tables recommend that have no crop-data row (so no ALIASES entry)
EXTRA_MENTIONS = ["ajwain", "azwain", "cumin", "isabgol", "fennel", "henna", "mehandi", "lucerne", "napier"]
_MENTION = re.compile(
    r"(?<![A-Za-z])(?i:(" + "|".join(
        r"\s*".join(map(re.escape, a.split()))
        for a in sorted({a for names in ALIASES.values() for a in names} | set(EXTRA_MENTIONS),
                        key=len, reverse=True))
    + r"|fallow))(?![a-z])")


_NEGATION = re.compile(r"\b(avoid|instead\s+of|in\s+place\s+of|replace|not\s+(?:to\s+)?(?:grow|sow))\b", re.I)
# what may sit between crops of one negated list: 'green gram, groundnut and soybean', 'Kharif Sorghum + Pigeon pea sowing'
_LIST_GAP = re.compile(r"^(?:[\s,/&+\-–—:()]|\band\b|\bor\b|\bkharif\b|\brabi\b|\bsole\b|\bsowing\b|\bcrops?\b)*$", re.I)


def crop_mentions(text, skip_negated=False):
    """Crop names written in a free-text cell, in order, as written ('Fallow' counts too).
    'Fallow-Mustard (Bio-902)/gram' -> ['Fallow', 'Mustard', 'gram'].
    skip_negated leaves out crops the cell says not to grow: 'Avoid Soybean. Go for Tobacco',
    'Replace wheat by mustard', 'sunflower or maize instead of cotton'."""
    text = text or ""
    negated = set()
    if skip_negated:
        for n in _NEGATION.finditer(text):
            end = n.end()
            for m in _MENTION.finditer(text, n.end()):
                if not _LIST_GAP.match(text[end:m.start()]):
                    break  # the negated list ended ('go for', 'by', 'based on', '.')
                negated.add(m.start())
                end = m.end()
    out = []
    for m in _MENTION.finditer(text):
        if m.start() in negated:
            continue
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        k, crop = key(name), ALIAS_INDEX.get(key(name))
        # skip repeats: 'Pigeon pea'/'Pigeonpea', and 'moth' inside a variety after 'Moth bean'
        if any(k == key(o) or (crop and crop == ALIAS_INDEX.get(key(o)) and k in key(o)) for o in out):
            continue
        out.append(name)
    return out


@lru_cache(maxsize=1)
def _crop_table():
    import pandas as pd
    return pd.read_csv(CROPS_CSV, usecols=["year", "state_name", "district_name", "crop_name",
                                           "crop_type", "season", "area"])


@lru_cache(maxsize=1)
def _crosswalk():
    with open(CROSSWALK, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def crop_districts(state, plan_district):
    """Crop-data district names that make up a plan district (handles renames/splits)."""
    pd_key = key(plan_district)
    return sorted({r["crop_district"] for r in _crosswalk()
                   if r["state"] == state and key(r["plan_district"] or "") == pd_key})


def district_crops(state, plan_district):
    """{crop_name: max yearly area in ha} over 1997-2023 for the plan district."""
    t = _crop_table()
    states = {state, "Andhra Pradesh"} if state == "Telangana" else {state}
    rows = t[t.state_name.isin(states) & t.district_name.isin(crop_districts(state, plan_district))
             & (t.season != "Total") & (t.area > 0)]
    return rows.groupby(["crop_name", "year"]).area.sum().groupby("crop_name").max().to_dict()


RECENT_FROM = "2010"  # decision rules v2: a crop with no data from 2010-11 on counts as missing


def state_field_crops(state, min_districts=5):
    """Field crops grown (area > 0) from 2010-11 on in at least `min_districts` districts of the
    state, so that a check under decision rules v2 can find them in the crop data."""
    t = _crop_table()
    field = {"Cereals", "Pulses", "Oilseeds", "Fiber Crops", "Sugar"}
    rows = t[(t.state_name == state) & t.crop_type.isin(field) & (t.area > 0) & (t.year >= RECENT_FROM)]
    n = rows.groupby("crop_name").district_name.nunique()
    return sorted(c for c, k in n.items() if k >= min_districts and not c.startswith("Other"))


@lru_cache(maxsize=None)
def state_recent_crops(state):
    """Crop-data names with area > 0 anywhere in the state from 2010-11 on."""
    t = _crop_table()
    return frozenset(t[(t.state_name == state) & (t.area > 0) & (t.year >= RECENT_FROM)].crop_name)


def claim_crop_names():
    """Counter of every crop string in the claims, with one example claim_id each."""
    counts, example = Counter(), {}
    for d in CLAIM_DIRS:
        for f in d.glob("*/*.jsonl"):
            if f.parent.name.startswith("_"):
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                c = json.loads(line)
                for name in [c.get("crop"), c.get("normal_crop")] + c.get("recommended_crops", []):
                    if name and key(name) not in ("nochange", ""):
                        counts[name.strip()] += 1
                        example.setdefault(name.strip(), c["claim_id"])
    return counts, example


def write_crop_names():
    counts, example = claim_crop_names()
    known = set(_crop_table().crop_name.unique())
    types = _crop_table().drop_duplicates("crop_name").set_index("crop_name").crop_type.to_dict()
    rows = []
    for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        hit = to_crop_data_name(name)
        match = ("exact" if hit and key(hit) == key(name) else "alias") if hit else "none"
        assert hit is None or hit in known, hit
        rows.append({"plan_crop_name": name, "crop_data_name": hit or "", "crop_type": types.get(hit, ""),
                     "match": match, "n_claims": n, "example_claim_id": example[name],
                     "checked_by_person2": ""})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["plan_crop_name"])
        w.writeheader()
        w.writerows(rows)
    unmatched = [r["plan_crop_name"] for r in rows if r["match"] == "none"]
    print(f"{len(rows)} crop names, {len(unmatched)} unmatched -> {OUT}")
    if unmatched:
        print("unmatched:", ", ".join(unmatched[:40]))


if __name__ == "__main__":
    write_crop_names()
