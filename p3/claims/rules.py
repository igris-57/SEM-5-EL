"""Rule-based Claim Extractor for the fixed profile tables of the CRIDA template (no LLM).

  1.2  normal rainfall, rainy days, onset, cessation   (from page text)
  1.7  total area under each crop                      (from rebuilt tables)
  1.11 production / productivity per crop and season   (from rebuilt tables)
  1.12 sowing window per crop and season               (from rebuilt tables)
  1.13 hazard proneness: regular / occasional / none   (from rebuilt tables)

Every claim goes through the same checks as the LLM claims (checks.check_claim).

    python -m p3.claims.rules --all        # or --plans Karnataka/Udupi
Writes claims_rules/<State>/<District>.jsonl and claims_rules/summary.csv.
"""
import argparse
import csv
import json
import re
from pathlib import Path

from pydantic import ValidationError

from p3.crops import NON_CSV_CROPS, crop_mentions, to_crop_data_name

from .checks import check_claim
from .dates import parse_point, parse_range
from .schema import Claim, StoredClaim

ROOT = Path(__file__).resolve().parents[2]
PLAN_TEXT = ROOT / "plan_text"
OUT = ROOT / "claims_rules"
RULES_VERSION = "rules-v1"

SEASON_LABELS = [  # (regex on a text line, season)
    (r"^\s*(S\.?\s*W\.?\s*monsoon|kharif\s*\(\s*june)", "sw_monsoon"),  # Hassan: 'Kharif (June-Sep)'
    (r"^\s*(N\.?\s*E\.?\s*monsoon|post[- ]rainy|rabi\s*\(\s*oct)", "ne_monsoon"),
    (r"^\s*winter", "winter"),
    (r"^\s*summer", "summer"),
    (r"^\s*annual\b", "annual"),
]
HAZARDS = [(r"drought", "drought"), (r"flood", "flood"), (r"cyclone", "cyclone"),
           (r"hail", "hailstorm"), (r"heat\s*wave", "heat_wave"), (r"cold\s*wave", "cold_wave"),
           (r"frost", "frost"), (r"sea\s*water", "sea_water_intrusion"),
           (r"pest", "pests_diseases")]
#  is a tick drawn in a symbol font (Palghar). \x01 is one too in Chitradurga & co., but
# in Chikmagalur it is a stray box on a cell border, so it only counts when a row has no other tick
TICK = re.compile(r"[√✓✔]|^\s*(yes|y|\*)\s*$", re.I)
WEAK_TICK = re.compile(r"\x01")
NUM = re.compile(r"^\s*(\d+(?:\.\s?\d+)?)\s*$")
EMPTY = re.compile(r"^\s*[-–—]*\s*$")
MONTH_RE = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
_MONTH_OR_WEEK =r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|week|fortnight|\bFN\b|\bMW\b"


def rows_of(md):
    return [[c.strip() for c in line.strip().strip("|").split("|")] for line in md.split("\n")]


RABI_CROPS = {"Wheat", "Gram", "Barley", "Rapeseed &Mustard", "Safflower", "Linseed", "Masoor"}


def kharif_rabi_pair(crop):
    """('Guar', 'Gram') for a label pairing a kharif and a rabi crop ('(Guar/ Gram)',
    'A. cotton / Wheat'); None for one combined entry like 'Green gram / Black gram'."""
    pair = [p.strip(" ():") for p in (crop or "").split("/")]
    if len(pair) == 2 and all(re.search(r"[A-Za-z]{3}", p) for p in pair) \
            and to_crop_data_name(pair[1]) in RABI_CROPS \
            and (crop_mentions(pair[0]) or to_crop_data_name(pair[0])) \
            and to_crop_data_name(pair[0]) not in RABI_CROPS:
        return pair[0], pair[1]
    return None


def filled_tables(page):
    """page['tables'] with each vertically merged cell repeated on every row it covers
    (page['table_merges'] from extract_text.py); plain tables for older plan_text files."""
    merges = page.get("table_merges") or []
    out = []
    for ti, t in enumerate(page.get("tables", [])):
        rows = rows_of(t)
        for r, c, src in (merges[ti] if ti < len(merges) else []):
            if r < len(rows) and src < len(rows) and c < len(rows[r]) and c < len(rows[src]) \
                    and not rows[r][c]:
                rows[r][c] = rows[src][c]
        out.append("\n".join("| " + " | ".join(r) + " |" for r in rows))
    return out


def num(cell):
    if re.match(r"^\s*0\d{2,}\s*$", cell or ""):
        return None  # '0640' (for 0.640?) is ambiguous: never read it as 640
    m = NUM.match(cell or "")
    return float(m.group(1).replace(" ", "")) if m else None


def is_crop_cell(cell):
    c = (cell or "").strip()
    if not c or num(c) is not None or EMPTY.match(c) or not re.search(r"[A-Za-z]{3}", c) or len(c) >= 40:
        return False
    if re.search(r"total|area|major|(?<!cole )crops?\b", c, re.I) or \
            re.fullmatch(r"\s*(others?|nursery|pre\s*-?\s*monsoon)\s*", c, re.I):
        return False
    if re.search(r"irrigated|rainfed|kharif|rabi|summer", c, re.I):
        # a season label ('Kharif-Rainfed') or a crop with one ('Rabi Sorghum', 'Paddy -Rainfed')
        rest = re.sub(r"irrigated|rainfed|kharif|rabi|summer|[-–:()]", " ", c, flags=re.I)
        return bool(to_crop_data_name(rest.strip()))
    return True


def claim(**kw):
    try:
        return Claim(**kw)
    except ValidationError:
        return None


# ---------- 1.2 rainfall (page text) ----------

def rainfall_claims(page):
    lines = page["text"].split("\n")
    start = next((i for i, l in enumerate(lines) if re.match(SEASON_LABELS[0][0], l, re.I)), None)
    if start is None:
        return []
    out, seen = [], set()
    # some plans add an actual-rainfall column for one year ("RF(mm) 2009") between normal
    # rainfall and rainy days; '-' cells are lost in page text, so then rainy days need 3 numbers
    head = " ".join(lines[max(0, start - 15):start])
    year_col = bool(re.search(r"(?:RF|rainfall)\s*\(mm\)\s*\(?\s*(?:19|20)\d\d", head, re.I))
    i = start
    while i < min(len(lines), start + 80):
        label = lines[i]
        season = next((s for pat, s in SEASON_LABELS if re.match(pat, label, re.I)), None)
        if not season:
            if re.match(r"^\s*1\.3\b", label):
                break
            i += 1
            continue
        if season in seen:
            break
        seen.add(season)
        cells, j = [], i + 1
        while j < len(lines) and len(cells) < 6:  # rainfall, (year rainfall), days, onset, cessation
            l = lines[j].strip()
            if any(re.match(p, l, re.I) for p, _ in SEASON_LABELS) or re.match(r"^1\.3\b", l):
                break
            if re.search(r"monsoon|shower|winter|summer|annual", l, re.I):
                break  # another row's label ('Post monsoon shower'): never borrow its numbers
            if l and cells and num(cells[-1]) is None and not EMPTY.match(cells[-1]) and (
                    (re.match(r"^[(a-z]", l) and not (parse_point(l) and parse_point(cells[-1])))
                    or re.search(r"\bof$", cells[-1])):  # '4th week of' + 'June' (Jalore)
                cells[-1] += " " + l  # rest of a cell: '25th Standard Week' + '(3rd week of June)'
            elif l:
                cells.append(l)
            j += 1
        nums = [(c, num(c)) for c in cells if num(c) is not None]
        # onset is the 1st date cell and cessation the 2nd, by position: an onset we cannot read
        # must not shift the cessation into the onset slot (Haveri)
        dates = [c for c in cells if re.search(_MONTH_OR_WEEK, c, re.I)][:2]
        lab = label.strip()
        if nums:
            c, v = nums[0]
            out.append(claim(claim_type="rainfall_normal", season=season, metric="rainfall_mm",
                             value=v, quote_parts=[lab, c],
                             statement=f"Normal {lab.rstrip(':')} rainfall is {c} mm."))
        days_i = 2 if year_col else 1
        if len(nums) > days_i:
            c, v = nums[days_i]
            out.append(claim(claim_type="rainfall_normal", season=season, metric="rainy_days",
                             value=v, quote_parts=[lab, c],
                             statement=f"Normal {lab.rstrip(':')} rainy days are {c}."))
        for kind, d in zip(["monsoon_onset", "monsoon_cessation"], dates):
            if not parse_point(d):
                continue
            m, w = parse_point(d)
            word = "onset" if kind == "monsoon_onset" else "cessation"
            out.append(claim(claim_type=kind, season=season, start_month=m, start_week=w,
                             quote_parts=[lab, d], statement=f"Normal {lab.rstrip(':')} {word} is {d}."))
        i = j
    return [c for c in out if c]


# ---------- tables ----------

def find_tables(page, pattern):
    return [t for t in page.get("tables", []) if re.search(pattern, t[:400], re.I)]


def hazard_claims(page, carry=None):
    """carry (one dict per plan) remembers the tick columns, so a table that runs on to the
    next page without its header is still read (14 plans, e.g. Chitradurga p7-8)."""
    carry = {} if carry is None else carry
    out = []
    tables = [(t, False) for t in find_tables(page, r"contingency the district|district is prone")]
    first = page.get("tables", [])[:1]
    if first and carry.get("page") == page["page"] - 1 and not tables:
        rows = rows_of(first[0])
        if len(rows[0]) == carry["width"] and \
                sum(any(re.search(p, c, re.I) for c in r[:3]) for r in rows for p, _ in HAZARDS) >= 2:
            tables = [(first[0], True)]
    for t, continued in tables:
        rows = rows_of(t)
        if continued:
            head, cols = None, carry["cols"]
        else:
            head = next((r for r in rows if any(re.match(r"regular", c, re.I) for c in r)), None)
            if not head:
                continue
            cols = {k: next((i for i, c in enumerate(head) if re.match(k, c, re.I)), None)
                    for k in ("regular", "occasional", "none")}
            if None in cols.values():
                continue
            carry.update(cols=cols, width=max(len(r) for r in rows), page=page["page"])
        for r in rows:
            name = next((c for c in r[:3] if re.search(r"[A-Za-z]{4}", c)), "")
            hz = next((h for pat, h in HAZARDS if re.search(pat, name, re.I)), None)
            if not hz or r is head:
                continue
            ticked = [k for k, i in cols.items() if i < len(r) and TICK.search(r[i] or "")] or \
                [k for k, i in cols.items() if i < len(r) and WEAK_TICK.search(r[i] or "")]
            if len(ticked) == 1:
                cell = r[cols[ticked[0]]]
                out.append(claim(claim_type="hazard_proneness", hazard=hz, frequency=ticked[0],
                                 quote_parts=[name, cell],
                                 statement=f"{name} is marked '{ticked[0]}' among contingencies the district is prone to."))
    return [c for c in out if c]


SOW_ROW = [(r"kharif", "kharif"), (r"rabi", "rabi"), (r"summer", None)]


def sowing_claims(page):
    out = []
    for t in find_tables(page, r"sowing window"):
        rows = rows_of(t)
        head_i = next((i for i, r in enumerate(rows) if any(re.search(r"sowing window", c, re.I) for c in r)), None)
        if head_i is None:
            continue
        head = rows[head_i]
        for r in rows[head_i + 1:]:
            lab_i = next((i for i, c in enumerate(r) if re.search(r"kharif|rabi", c, re.I)), None)
            rest = [c for c in r[(lab_i if lab_i is not None else 1) + 1:] if c and not EMPTY.match(c)]
            if len(rest) >= 2 and all(to_crop_data_name(c) for c in rest):
                # a crop sub-header for the rows below, with or without a season label:
                # '| Rabi | Sorghum | Gram | Wheat |' (Chandrapur), '| | Wheat | Sorghum | Gram |' (Parbhani)
                head = r
                continue
            if lab_i is None:
                continue
            lab = r[lab_i]
            season = next(s for p, s in SOW_ROW if re.search(p, lab, re.I))
            water = "irrigated" if re.search(r"irrig", lab, re.I) else "rainfed" if re.search(r"rainfed", lab, re.I) else None
            for ci in range(lab_i + 1, min(len(r), len(head))):
                cell, crop = r[ci], re.sub(r"^\s*(?:crop\s*)?\d*\s*:\s*", "", head[ci], flags=re.I)  # '4 : Green gram', ': Sunflower'
                pair = kharif_rabi_pair(crop)
                if pair:
                    crop = pair[0] if season == "kharif" else pair[1]  # '(Guar/ Gram)': kharif / rabi crop
                if not cell or EMPTY.match(cell) or not is_crop_cell(crop):
                    continue
                lead = re.match(r"^\s*([A-Za-z][A-Za-z .]*?[A-Za-z])\s+(?=\d)", cell)  # 'Isabgol 1st - 31st Nov'
                if lead and len(lead.group(1)) >= 4 and \
                        not re.search(rf"{MONTH_RE}|iune|week|fortnight|mid|end|last|first|kharif|rabi|summer|"
                                      r"irrigated|rainfed|pre|^(to|from|upto)\b", lead.group(1), re.I):
                    crop = lead.group(1)
                note = re.search(r"\(([A-Za-z][A-Za-z ]+)\)", cell)
                if note and not re.fullmatch(r"\s*(kharif|rabi|summer|irrigated|rainfed|pre\s*-?\s*monsoon)\s*",
                                             note.group(1), re.I):  # '(Cumin)' yes, '(Kharif)', '(Premonsoon)' no
                    crop = note.group(1).strip()
                rng = parse_range(cell)
                if not rng:
                    continue
                (m1, w1), (m2, w2) = rng
                out.append(claim(claim_type="sowing_window", crop=crop, season=season,
                                 water_regime=water, start_month=m1, start_week=w1,
                                 end_month=m2, end_week=w2, quote_parts=[lab, cell],
                                 statement=f"Normal sowing window of {crop} ({lab}) is {cell}."))
    return [c for c in out if c]


def _header_labels(header_rows, width):
    labels = [""] * width
    season = [""] * width
    for r in header_rows:
        cur = ""
        for i in range(width):
            c = r[i] if i < len(r) else ""
            if re.search(r"kharif|rabi|summer|total", c, re.I) and not re.search(r"production|productivity", c, re.I) \
                    and not re.search(r"irrigated|rainfed", c, re.I):
                cur = c
            if c:
                labels[i] = (labels[i] + " " + c).strip()
            if cur and not season[i]:
                season[i] = cur
            elif c and re.search(r"kharif|rabi|summer|total", c, re.I):
                season[i] = c
    return labels, season


def production_claims(page, carry=None):
    """carry (one dict per plan) keeps the last table's header, so the same table running on to
    the next page without its header is still read (33 plans, e.g. Mahabubnagar p7)."""
    carry = {} if carry is None else carry
    out = []
    tables = [(t, None) for t in find_tables(page, r"productivity")]
    first = page.get("tables", [])[:1]
    if not tables and first and carry.get("page") == page["page"] - 1 \
            and not re.search(r"sowing window|prone to|1\.1[2-9]", first[0][:400], re.I) \
            and len(rows_of(first[0])[0]) == carry["width"]:
        tables = [(first[0], carry)]
    for t, cont in tables:
        rows = rows_of(t)
        width = max(len(r) for r in rows)
        if cont:
            header, labels, season, ref = [], cont["labels"], cont["season"], cont["ref"]
            carry["page"] = page["page"]  # it may run on for one more page
        else:
            header = [r for r in rows[:4] if any(re.search(r"production|productivity|kharif|rabi", c, re.I) for c in r)]
            labels, season = _header_labels(header, width)
            ref = re.search(r"(20\d\d(?:\s*[-–]\s*\d{2,4})?)", " ".join(" ".join(r) for r in header))
            carry.update(labels=labels, season=season, ref=ref, width=width, page=page["page"])
        for r in rows:
            if r in header:
                continue
            ci = next((i for i, c in enumerate(r[:3]) if is_crop_cell(c)), None)
            if ci is None:
                continue
            crop = r[ci]
            # some plans pair a kharif and a rabi crop in one row: 'Guar/Gram | 109.0 | 604 | 134.7 | 617'
            pair = kharif_rabi_pair(crop)
            cur, switched = (pair[0] if pair else crop), bool(pair)
            for i in range(ci + 1, len(r)):
                cell = r[i]
                lab = labels[i] if i < width else ""
                # ...or write the rabi crop inside the row: 'Bajra | 152 | 1460 | 464.033 Wheat | 3422'
                m = re.match(r"^\s*(?P<v>\d+(?:\.\d+)?)\s+(?P<c>[A-Za-z][A-Za-z .&-]+)$", cell) or \
                    re.match(r"^\s*(?P<c>[A-Za-z][A-Za-z .&]+?)\s*-\s*(?P<v>\d+(?:\.\d+)?)\s*$", cell)  # 'Gram - 20.2'
                if m and to_crop_data_name(m.group("c").strip()):
                    cur, switched, v, txt = m.group("c").strip(), True, float(m.group("v")), m.group("v")
                elif is_crop_cell(cell) and to_crop_data_name(cell):
                    cur, switched = cell, True  # 'Cotton | 77.1 | 21.4 | Gram | 35.8 | 63.4'
                    continue
                else:
                    v, txt = num(cell), cell
                if not lab and i > ci + 1 and is_crop_cell(r[i - 1]):
                    lab = labels[i - 1]  # the crop name took this value's header column
                elif not lab and i + 1 < width and labels[i + 1] and (i + 1 >= len(r) or not r[i + 1].strip()):
                    lab = labels[i + 1]  # header one column right of its values (Sangli 'Average Productivity')
                s = season[i].lower() if i < width else ""
                if lab and i < width and not labels[i] and "total" in season[i - 1].lower():
                    s = season[i - 1].lower()  # ...under the same 'Total' heading as the column before
                if v is None or "fodder" in lab.lower() or "summer" in s:
                    continue  # summer is not a schema season; the Total column covers it
                sea = "kharif" if "kharif" in s else "rabi" if "rabi" in s else None
                total = "total" in s
                if total and switched:
                    continue  # a total over two different crops
                if pair and sea == "rabi":
                    cur = pair[1]
                metric = ("productivity_kg_ha" if re.search(r"productiv|kg", lab, re.I)
                          else "production_000t" if re.search(r"production|prod\.", lab, re.I) else None)
                if metric == "production_000t" and re.search(r"\(", lab) and not re.search(r"000", lab):
                    continue  # production given in tonnes / '00 MT / quintals, not '000 t
                if not ((sea or total) and metric):
                    continue
                word = "productivity" if metric == "productivity_kg_ha" else "production"
                unit = "kg/ha" if word == "productivity" else "'000 t"
                when = sea.title() if sea else "Total (all seasons)"
                out.append(claim(claim_type="crop_production", crop=cur, season=sea, metric=metric,
                                 value=v, ref_year=ref.group(1) if ref else None,
                                 quote_parts=[cur, cell],
                                 statement=f"{when} {word} of {cur} is {txt} {unit}."))
    return [c for c in out if c]


def area_claims(page, carry=None):
    """carry (one dict per plan) keeps the column headings, so the table running on to the
    next page without its header is still read (Chitradurga p4)."""
    carry = {} if carry is None else carry
    out = []
    tables = [(t, None) for t in find_tables(page, r"major field crops cultivated|area under")]
    if tables:  # horticulture / plantation sub-tables printed right after the main one (Churu)
        all_t = page.get("tables", [])
        last = max(all_t.index(t) for t, _ in tables)
        for t in all_t[last + 1:]:
            if not re.search(r"horticultur|plantation crops|medicinal", t[:200], re.I) or \
                    re.search(r"productivity|production|sowing window", t[:400], re.I):
                break
            if not re.search(r"000", t[:400]):
                continue  # only a sub-table that says '000 ha itself (Akola's is in ha, Haveri's says nothing)
            tables.append((t, {"sub": True}))
    first = page.get("tables", [])[:1]
    if not tables and first and carry.get("page") == page["page"] - 1 \
            and not re.search(r"productivity|sowing window|prone to|1\.[89]\b|1\.1\d", first[0][:400], re.I) \
            and len(rows_of(first[0])[0]) == carry["width"]:
        tables = [(first[0], carry)]
    for t, cont in tables:
        rows = rows_of(t)
        sub = bool(cont and cont.get("sub"))
        cont = None if sub else cont
        if not cont and not sub and not re.search(r"000\s*[’'`]?\s*ha|'000|‘000|000ha|000’ha", t, re.I):
            continue  # area not in '000 ha (a sub-table uses the main table's unit)
        ref = cont["ref"] if cont else (re.search(r"\((20\d\d\s*[-–]\s*\d{2,4})\)", t[:300]) or
                                        re.search(r"\((20\d\d\s*[-–]\s*\d{2,4})\)", page["text"][:600]))
        width = max(len(r) for r in rows)
        if cont:
            labels, groups = list(cont["labels"]), list(cont["groups"])
            width = max(width, len(labels))
            labels += [""] * (width - len(labels))
            groups += [""] * (width - len(groups))
            carry["page"] = page["page"]
        else:
            labels = [""] * width
            groups = [""] * width  # the season / 'Total' heading over each column
        in_header = fodder = False
        in_ha = False  # under a '(ha)' sub-heading (Raichur, Pratapgarh, Sirohi horticulture rows)
        for r in rows:
            nums = [num(c) for c in r if num(c) is not None]
            crop_cells = [i for i, c in enumerate(r) if is_crop_cell(c)]
            if not nums:
                heading = " ".join(r)
                if re.search(r"000", heading):
                    in_ha = False
                elif re.search(r"\(\s*ha\s*\)", heading, re.I):
                    in_ha = True
            if in_ha:
                continue
            if any(re.search(r"fodder|grazing|sericulture|others", c, re.I) for c in r[:4]):
                fodder = not nums or fodder  # a fodder sub-table header, or a row inside it
                continue
            if fodder and nums:
                continue
            if nums and not crop_cells:
                continue  # a data row we cannot name: never let it overwrite the header labels
            if not nums:  # header row: update column labels
                fodder = False
                if any(re.search(r"irrigated|rainfed|total", c, re.I) for c in r):
                    if not in_header:
                        labels, groups = [""] * width, [""] * width
                    if any(re.search(r"kharif|rabi", c, re.I) for c in r):  # the season heading row
                        cur = ""
                        for i, c in enumerate(r):
                            cur = c if re.search(r"kharif|rabi|summer|total", c, re.I) else cur
                            groups[i] = cur
                    for i, c in enumerate(r):
                        if c:
                            labels[i] = c
                    in_header = True
                continue
            in_header = False
            bounds = crop_cells + [len(r)]
            multi = len(crop_cells) > 1
            for a, b in zip(bounds, bounds[1:]):
                totals = [i for i in range(a + 1, b) if i < width
                          and re.match(r"(grand\s+)?total", labels[i], re.I)
                          and not (multi and re.search(r"grand", labels[i], re.I))]
                cols = [i for i in totals if num(r[i]) is not None]
                # 'Grand total' (all seasons) beats the per-season 'Total' columns before it:
                # Dhule Groundnut 35.7 kharif + 0.1 summer = 35.8
                grand = [i for i in cols if re.match(r"grand", labels[i], re.I)]
                cols = grand or cols
                crop = r[a]
                if not totals:
                    # 'Total' split into Irrigated / Rainfed columns only (Chamarajanagar)
                    for i in range(a + 1, b):
                        reg = re.search(r"irrigated|rainfed", labels[i] if i < width else "", re.I)
                        if i < width and reg and re.match(r"total", groups[i], re.I) and num(r[i]) is not None:
                            w = reg.group(0).lower()
                            out.append(claim(claim_type="crop_area", crop=crop, water_regime=w,
                                             metric="area_000ha", value=num(r[i]),
                                             ref_year=ref.group(1) if ref else None,
                                             quote_parts=[crop, r[i]],
                                             statement=f"Total {w} area under {crop} is {r[i]} '000 ha."))
                    continue
                if not cols:
                    continue
                pair = kharif_rabi_pair(crop)
                if pair:
                    # 'Guar / Barley | - | - | 247.4 | - | - | 48.4': kharif crop / rabi crop
                    if len(cols) == 2:
                        for p, i, sea in zip(pair, cols, ("kharif", "rabi")):
                            out.append(claim(claim_type="crop_area", crop=p, season=sea,
                                             metric="area_000ha", value=num(r[i]),
                                             ref_year=ref.group(1) if ref else None,
                                             quote_parts=[crop, r[i]],
                                             statement=f"{sea.title()} area under {p} is {r[i]} '000 ha."))
                    continue
                i = cols[-1]
                out.append(claim(claim_type="crop_area", crop=crop, metric="area_000ha",
                                 value=num(r[i]), ref_year=ref.group(1) if ref else None,
                                 quote_parts=[crop, r[i]],
                                 statement=f"Total area under {crop} is {r[i]} '000 ha."))
        if not cont:  # the next page continues with the headings in force at the table's end
            carry.update(labels=labels, groups=groups, ref=ref,
                         width=max(len(r) for r in rows), page=page["page"])
    return [c for c in out if c]


EXTRACTORS = [rainfall_claims, area_claims, production_claims, sowing_claims, hazard_claims]


# ---------- 2.1 drought contingency tables (rows carry over across pages) ----------

NON_DROUGHT = re.compile(
    r"canal|tank|ground\s*water|bore\s*well|irrigated situation|water\s*logging|high rainfall|"
    r"recharge|release of water|"
    r"unusual|flood|cyclone|hail|heat\s*wave|cold\s*wave|frost|feed|fodder|drinking water|"
    r"disease management|poultry|bird|livestock|animal|cattle|fish|"
    r"crop maturity|post harvest|supplementation|sanitation", re.I)
DITTO = re.compile(r"^\s*(-*\s*do\s*-*|as above|same as above|\"|〃)\s*$", re.I)
IRRIGATED_HEAD = re.compile(r"2\.1\.2|irrigated situation|\b2\.2\s+unusual|unusual rains", re.I)
JOIN = " "  # joins the two halves of a cell split by a page break (each half is quoted)


def classify_condition(section, detail):
    """(condition, delay_weeks, dry_min, dry_max) from the table's section label + row label."""
    s = f"{section} {detail}"
    m = re.search(r"delay(?:ed)?\s*(?:by|of)?\s*(\d+)\s*weeks?", s, re.I)
    if m:
        return "delayed_onset", int(m.group(1)), None, None
    if re.search(r"terminal|early withdrawal|withdrawal of monsoon", s, re.I):
        return "terminal_drought", None, None, None
    if re.search(r"flower|fruit|reproduct|grain fill|pod", detail, re.I) or \
            (re.search(r"flower|reproduct", section, re.I) and not re.search(r"vegetat", detail, re.I)):
        return "mid_season_drought_flowering", None, None, None
    if re.search(r"vegetat", s, re.I):
        return "mid_season_drought_vegetative", None, None, None
    if re.search(r"mid[- ]?season", s, re.I):
        return None, None, None, None  # mid-season with no crop stage given: do not guess one
    d = re.search(r"(\d+)\s*[-–to]+\s*(\d+)\s*days?", s, re.I)
    if re.search(r"dry spell|normal onset", s, re.I):
        return "early_dry_spell", None, int(d.group(1)) if d else None, int(d.group(2)) if d else None
    return None, None, None, None


def recommended(cell):
    """Crops named in a 'change in crop' cell, as written ('Fallow' included);
    ['No change']; None if the cell only names varieties of the same crop."""
    found = crop_mentions(cell.replace(JOIN, " "), skip_negated=True)  # not 'Avoid Soybean'
    alt = re.match(r"^\W*no change\s*(?:/|\bor\b)(.*)$", cell, re.I | re.S)
    if alt:  # 'No change / Soybean + pigeon pea 4:2': no change, or this alternative
        return ["No change"] + crop_mentions(alt.group(1).replace(JOIN, " "), skip_negated=True)
    if re.match(r"^\W*no change", cell, re.I) or (re.search(r"no change", cell, re.I) and not found):
        return ["No change"]  # 'No change Prefer JS-335' (varieties of the same crop)
    return found or None


def measures_of(cell):
    cell = cell.replace(JOIN, " ")
    # bullets, or list numbers '1)' at the start / after a space (not 'T-9)' in a variety name)
    parts = [p.strip(" .;") for p in re.split(r"\s*[•●▪]\s*|(?:^|\s)\d\)\s*", cell) if p.strip(" .;-")]
    return parts or [cell]


def flat(cell):
    return re.sub(r"\s+", " ", cell.replace(JOIN, " ")).strip()


def frags(cells):
    """Quote fragments: a cell split by a page break is quoted as its two halves."""
    return [f.strip() for c in cells for f in c.split(JOIN) if f.strip()]


def _table_pos(text, table_md):
    """Where the table starts in the page text (first long cell found), or None."""
    flat_text = re.sub(r"\s+", " ", text)
    for c in (c for r in rows_of(table_md) for c in r):
        c = re.sub(r"\s+", " ", c).strip()
        if len(c) >= 8:
            k = flat_text.find(c)
            if k >= 0:
                return k
    return None


def _continues(prev, row):
    """True if `row` (first row on a page) is the rest of `prev` (last row of the page before):
    a cell starts mid-sentence, e.g. 'of Nitrogen after restart of rains'."""
    if abs(len(prev) - len(row)) > 1 or \
            re.search(r"condition|major\s+farming", " ".join(prev + row), re.I):
        return False  # header rows are never joined (tables may differ by an empty last column)
    return any(c and p and re.match(r"^[a-z]", c) for c, p in zip(row[1:], prev[1:]))


def drought_rows(plan, start_page):
    """[{'page', 'pages', 'cells'}] for every table row from the 2.0 strategies page on, with
    vertically merged cells filled, rows split by a page break joined, and nothing after the
    2.1.2 (irrigated situation) heading."""
    items, irrigated = [], False
    for page in plan["pages"]:
        if page["page"] < start_page or page["low_text"] or irrigated:
            continue
        text = re.sub(r"\s+", " ", page["text"])
        head = IRRIGATED_HEAD.search(text)
        for ti, t in enumerate(filled_tables(page)):
            if head is not None:
                pos = _table_pos(page["text"], t)
                if pos is None or pos > head.start():
                    irrigated = True
                    break
            for k, r in enumerate(rows_of(t)):
                items.append({"page": page["page"], "pages": {page["page"]}, "cells": r,
                              "first": ti == 0 and k == 0})
    for a, b in zip(items, items[1:]):
        if b["first"] and b["page"] == a["page"] + 1 and _continues(a["cells"], b["cells"]):
            for i, (p, c) in enumerate(zip(a["cells"], b["cells"])):
                if p and c and re.match(r"^[a-z]", c):
                    a["cells"][i] = b["cells"][i] = p + JOIN + c
            a["pages"] = b["pages"] = a["pages"] | b["pages"]
    return items


def contingency_claims(plan, start_page):
    """Yield (page, claim, check_text) for the 2.1.1 rainfed drought tables."""
    st = {"section": "", "pending": "", "detail": "", "detail_page": None, "situation": "",
          "cols": None, "prev": {}}
    texts = {p["page"]: p["text"] for p in plan["pages"]}
    for item in drought_rows(plan, start_page):
        r, page_no = item["cells"], item["page"]
        joined = flat(" ".join(r))
        after_header, st["header"] = st.get("header"), False
        if sum(bool(re.search(r"(vegetative|flowering|maturity|harvest)\s*stage|post harvest", c, re.I))
               for c in r) >= 2:
            st["cols"] = None  # stage-wise table (2.2 unusual rains, 2.3 floods): not drought
            continue
        if re.search(r"major farming situation", joined, re.I):
            # the condition is in this row's first cell, or in a 'Condition <text>' row above it
            section = r[0] or st["pending"] or st["section"]
            # the same header repeated on the next page continues the table: keep its condition
            # ('Delay by 6 weeks' is only on the first page of the block, Gulbarga p15/17/19)
            same = flat(section) == flat(st["section"]) and st["cols"] is not None
            st["section"], st["pending"] = section, ""
            # only rainfed drought tables; irrigated (2.1.2), floods, livestock etc. are not parsed
            drought = re.search(r"drought|delayed onset|dry spell", st["section"], re.I) \
                and not NON_DROUGHT.search(st["section"])
            cols = classify_columns([flat(c) for c in r]) if drought else None
            if drought and cols is None and after_header:
                cols = st["cols"]  # 2nd line of a header split over two rows / pages
            st["cols"], st["header"] = cols, True
            if not same:
                st["detail"], st["situation"], st["prev"] = "", "", {}
            continue
        m = re.match(r"^\s*condition\b(.*)$", r[0], re.I)
        if m:
            st["pending"] = m.group(1).strip()
            if st["pending"] and NON_DROUGHT.search(st["pending"]):
                st["cols"] = None
            continue
        if st["cols"] is None:
            continue
        if re.search(r"unusual rain|flood|heat wave|cold wave|hail|cyclone|frost", joined, re.I) \
                and not re.search(r"drought", joined, re.I) and not any(r[1:]):
            st["cols"] = None  # leave the drought tables
            continue
        cols = st["cols"]
        cells = r + [""] * (len(cols) - len(r)) if len(r) < len(cols) else r
        if cells[0]:
            st["detail"], st["detail_page"] = flat(cells[0]), page_no
        if cols.get("situation") is not None and cells[cols["situation"]]:
            st["situation"] = flat(cells[cols["situation"]])
        crop = flat(cells[cols["crop"]]) if cols.get("crop") is not None else ""
        if not crop or DITTO.match(crop) or not re.search(r"[A-Za-z]{3}", crop):
            continue
        if not (crop_mentions(crop) or NON_CSV_CROPS.search(crop)) or \
                re.match(r"^\W*(no change|follow|apply|harvest)", crop, re.I):
            continue  # a sub-header ('Kharif'), soil type or stray text in the crop column
        if NON_DROUGHT.search(st["detail"]) or \
                (NON_DROUGHT.search(crop) and not re.search(r"fodder|feed", crop, re.I)):  # 'Rizka bajri fodder' is a crop
            continue
        cond, weeks, dmin, dmax = classify_condition(st["section"], st["detail"])
        if not cond:
            continue
        when = parse_point(st["detail"]) if cond == "delayed_onset" else None
        base = dict(condition=cond, delay_weeks=weeks, dry_spell_min_days=dmin,
                    dry_spell_max_days=dmax, normal_crop=crop,
                    farming_situation=st["situation"] or None,
                    start_month=when[0] if when else None,
                    start_week=when[1] if when else None)
        if cond == "mid_season_drought_vegetative":
            base["crop_stage"] = "vegetative"
        elif cond == "mid_season_drought_flowering":
            base["crop_stage"] = "flowering/reproductive"
        if cond != "delayed_onset" and cond != "early_dry_spell":
            base.update(delay_weeks=None)
        head = [st["detail"]] if st["detail"] else []
        pages = sorted(item["pages"] | {st["detail_page"] or page_no})
        check_text = "\n".join(texts[p] for p in range(pages[0], pages[-1] + 1) if p in texts)
        ctx = f"{st['detail'] or st['section']}".strip()

        ci = cols.get("change")
        meas_cols = cols.get("measures", [])
        short_crops = ci is not None and ci < len(cells) and len(flat(cells[ci])) <= 40 \
            and (recommended(cells[ci]) or ["No change"]) != ["No change"]
        if cond != "delayed_onset" and ci is not None and not short_crops:
            # some plans head a mid-season / terminal column 'Change in crop' but fill it with
            # crop management ('Stripping of older leaves'): read it as measures there. A short
            # cell naming crops is still a crop change ('Blackgram -> Greengram', Pratapgarh)
            ci, meas_cols = None, [cols["change"]] + meas_cols
        if ci is not None and ci < len(cells) and cells[ci] and not re.match(r"^\s*-+\s*$", cells[ci]):
            cell = cells[ci]
            if DITTO.match(cell):
                recs, src = st["prev"].get("recs"), st["prev"].get("recs_cell")
            else:
                recs, src = recommended(cell), cell
            if recs:
                st["prev"]["recs"], st["prev"]["recs_cell"] = recs, src
                c = claim(claim_type="contingency_crop_change", recommended_crops=recs,
                          quote_parts=frags(head + [crop, cell])[:6],
                          statement=f"{ctx}: for {crop}, the plan recommends: {flat(src)} "
                                    f"(crops: {', '.join(recs)}).", **base)
                if c:
                    yield page_no, c, check_text
            elif not DITTO.match(cell):
                st["prev"]["recs"] = None
        ms, quotes = [], []
        for mi in meas_cols:
            cell = cells[mi] if mi < len(cells) else ""
            if not cell or re.match(r"^\s*-+\s*$", cell):
                continue
            if DITTO.match(cell):
                got = st["prev"].get(mi)
            else:
                got = measures_of(cell)
                st["prev"][mi] = got
            if got:
                ms += got
                quotes.append(cell)
        if ci is not None and ci < len(cells) and cells[ci] and recommended(cells[ci]) is None \
                and not DITTO.match(cells[ci]) and not re.match(r"^\s*-+\s*$", cells[ci]):
            ms.insert(0, f"Varieties/crop choice: {flat(cells[ci])}")  # varieties of the same crop
            quotes.insert(0, cells[ci])
        if ms:
            c = claim(claim_type="contingency_measure", measures=ms[:12],
                      quote_parts=frags(head + [crop] + quotes)[:6],
                      statement=f"{ctx}: for {crop}, measures are {'; '.join(ms[:4])}"
                                f"{'...' if len(ms) > 4 else ''}.", **base)
            if c:
                yield page_no, c, check_text


def page_span(fragment, text):
    """The page-text passage a table cell came from, when the rebuilt cell lost subscript digits
    ('KNO /K SO' for 'KNO3/K2SO4'): same characters in order, allowing only extra digits and
    whitespace between them. None if the passage is not there."""
    # the subscripts land elsewhere in the cell ('KCl (1%) 3 2 4', 'KNO , urea and 3 DAP'): match on
    # everything but digits and spaces; the passage returned is the page's own text, digits in place
    chars = re.sub(r"[\s\d]+", "", fragment)
    if len(re.sub(r"[^A-Za-z]", "", chars)) < 15:
        return None
    pat = r"[\s\d₀-₉]*".join(map(re.escape, chars))
    m = re.search(pat, text)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None


def repair_quotes(c, text):
    """Swap each quote fragment that is not on the page for its page-text passage (and the same
    text in the measures and statement). None if any fragment cannot be found."""
    from .checks import quote_match
    swaps = {}
    for f in c.quote_parts:
        if quote_match(f, text) is None:
            span = page_span(f, text)
            if not span:
                return None
            swaps[f] = span
    data = c.model_dump()
    data["quote_parts"] = [swaps.get(f, f) for f in c.quote_parts]
    for old, new in swaps.items():
        data["measures"] = [m.replace(flat(old), new) for m in data.get("measures") or []]
        data["statement"] = data["statement"].replace(flat(old), new)
        old_parts, new_parts = measures_of(old), measures_of(new)
        if len(old_parts) == len(new_parts):  # bullets split the cell into several measures
            for o, n in zip(old_parts, new_parts):
                data["measures"] = [m.replace(o, n) for m in data["measures"]]
                data["statement"] = data["statement"].replace(o, n)
    return claim(**data)


def classify_columns(header):
    cols = {"measures": []}
    for i, h in enumerate(header):
        if re.search(r"farming situation", h, re.I):
            cols["situation"] = i
        elif re.search(r"normal crop|^\s*crop\s*/\s*cropping system", h, re.I):
            cols["crop"] = i
        elif re.search(r"change in crop", h, re.I):
            cols["change"] = i
        elif re.search(r"agronomic|crop management|soil nutrient|moisture conservation|rabi crop plan|measures", h, re.I) \
                and not re.search(r"remarks", h, re.I):
            cols["measures"].append(i)
    return cols if "crop" in cols else None


def extract_plan(plan_id):
    plan = json.loads((PLAN_TEXT / f"{plan_id}.json").read_text(encoding="utf-8"))
    stored, rejected = [], []
    done = {}  # extractor -> last page it found claims on: it may continue on the next page only
    carry = {fn: {} for fn in (hazard_claims, production_claims, area_claims)}
    for page in plan["pages"][:15]:  # profile section is in the first pages
        if page["low_text"]:
            continue
        for fn in EXTRACTORS:
            if fn in done and fn is not hazard_claims and \
                    (fn is rainfall_claims or page["page"] != done[fn] + 1):
                continue
            cs = fn(page, carry[fn]) if fn in carry else fn(page)
            if cs:
                done[fn] = page["page"]
            for c in cs:
                problems, match = check_claim(c, page["text"])
                if problems:
                    rejected.append({"page": page["page"], "problems": problems, "claim": c.model_dump()})
                    continue
                stored.append(StoredClaim(
                    **c.model_dump(), claim_id=f"{plan_id}#p{page['page']}#r{len(stored) + 1}",
                    plan_id=plan_id, state=plan["state"], district=plan["district"],
                    census_code_2011=plan.get("census_code_2011"), page=page["page"],
                    quote_match=match, model="rules", prompt_version=RULES_VERSION))
    start = next((p["page"] for p in plan["pages"]
                  if re.search(r"Strategies for weather|2\.0\s*Strategies", p["text"], re.I)), None)
    if start:
        for page_no, c, check_text in contingency_claims(plan, start):
            problems, match = check_claim(c, check_text)
            if problems and all(p.startswith("quote not on page") for p in problems):
                c = repair_quotes(c, check_text) or c
                problems, match = check_claim(c, check_text)
            if problems:
                rejected.append({"page": page_no, "problems": problems, "claim": c.model_dump()})
                continue
            stored.append(StoredClaim(
                **c.model_dump(), claim_id=f"{plan_id}#p{page_no}#r{len(stored) + 1}",
                plan_id=plan_id, state=plan["state"], district=plan["district"],
                census_code_2011=plan.get("census_code_2011"), page=page_no,
                quote_match=match, model="rules", prompt_version=RULES_VERSION))
    for folder, rows in ((OUT, [s.model_dump() for s in stored]), (OUT / "_rejected", rejected)):
        f = folder / f"{plan_id}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
                     encoding="utf-8")
    counts = {t: sum(s.claim_type.value == t for s in stored) for t in
              ("rainfall_normal", "monsoon_onset", "monsoon_cessation", "crop_area",
               "crop_production", "sowing_window", "hazard_proneness",
               "contingency_crop_change", "contingency_measure")}
    return {"plan_id": plan_id, **counts, "n_claims": len(stored), "n_rejected": len(rejected)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plans", nargs="+")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--planted", action="store_true",
                    help="read planted_text/ and write claims_rules_planted/")
    a = ap.parse_args()
    global PLAN_TEXT, OUT
    if a.planted:
        PLAN_TEXT, OUT = ROOT / "planted_text", ROOT / "claims_rules_planted"
    plans = (sorted(p.relative_to(PLAN_TEXT).with_suffix("").as_posix() for p in PLAN_TEXT.glob("*/*.json"))
             if a.all else a.plans)
    rows = [extract_plan(p) for p in plans]
    with open(OUT / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tot = {k: sum(r[k] for r in rows) for k in rows[0] if k != "plan_id"}
    print(f"{len(rows)} plans: {tot}")
    print("plans with no rainfall/onset:", [r["plan_id"] for r in rows if not r["rainfall_normal"]])


if __name__ == "__main__":
    main()
