"""
Builds data/district_crosswalk.csv: every district in the crop data -> its Census 2011 district
(the districts used by the plans and the DataMeet map).

    python build_crosswalk.py

Columns:
  state, crop_district, crop_district_code   as in data/crops/crop-wise-area-production-yield.csv
  map_district_2011, census_code_2011         as in data/map_2011/2011_Dist.dbf (DataMeet)
  plan_district                               as in contingency_plan_links.csv ("" = no plan)
  relation   same      = same district, same or older name
             renamed   = same area, new name
             split     = carved out after 2011 from this one 2011 district
             mixed     = carved out after 2011 mostly from this district, plus a few mandals of
                         another one (listed in note); assigned to the main parent
  series_group  districts to add together for a consistent 1997-2023 series (see note below)
  note

Pre-2011 splits: Chikkaballapura (from Kolar, 2007), Ramanagara (from Bangalore Rural, 2007),
Yadgir (from Gulbarga, 2010) and Pratapgarh (from Chittaurgarh/Udaipur/Banswara, 2008) are
2011 districts with their own plans, but before they existed their crops were counted in the
parent. For the drought-response check (2002 vs 2014-15), add up each series_group so 2002 and
2014 cover the same land. For checks using only 2011+ years, use map_district_2011 directly.

Mixed parents are from the 2016 Telangana reorganisation (G.O.s of 11 Oct 2016). Check the notes
against the official G.O.s before publishing.
"""
import csv
import struct

CROPS = "data/crops/crop-wise-area-production-yield.csv"
MAP_DBF = "data/map_2011/2011_Dist.dbf"
LINKS = "contingency_plan_links.csv"
OUT = "data/district_crosswalk.csv"
STATES = ["Karnataka", "Maharashtra", "Telangana", "Rajasthan"]

# crop-data name -> (2011 map name, relation, note). Names not listed are the same in both.
MAPPING = {
    "Karnataka": {
        "Bagalkote": ("Bagalkot", "renamed", ""),
        "Ballari": ("Bellary", "renamed", "lost Vijayanagara in 2021; add Vijayanagara back"),
        "Belagavi": ("Belgaum", "renamed", ""),
        "Bengaluru Rural": ("Bangalore Rural", "renamed", "lost Ramanagara in 2007; see series_group"),
        "Bengaluru Urban": ("Bangalore", "renamed", "no plan for this district"),
        "Bengaluru South": ("Ramanagara", "renamed", "Ramanagara, renamed Bengaluru South in 2025"),
        "Chamarajanagar": ("Chamrajnagar", "renamed", "spelling"),
        "Chikkamagaluru": ("Chikmagalur", "renamed", ""),
        "Kalaburagi": ("Gulbarga", "renamed", ""),
        "Mysuru": ("Mysore", "renamed", ""),
        "Shivamogga": ("Shimoga", "renamed", ""),
        "Tumakuru": ("Tumkur", "renamed", ""),
        "Vijayapura": ("Bijapur", "renamed", ""),
        "Vijayanagara": ("Bellary", "split", "formed 2021 from Ballari"),
    },
    "Maharashtra": {
        "Ahilyanagar": ("Ahmadnagar", "renamed", "Ahmednagar, renamed 2024"),
        "Beed": ("Bid", "renamed", "spelling"),
        "Buldhana": ("Buldana", "renamed", "spelling"),
        "Chhatrapati Sambhajinagar": ("Aurangabad", "renamed", "renamed 2023"),
        "Dharashiv": ("Osmanabad", "renamed", "renamed 2023"),
        "Gadchiroli": ("Garhchiroli", "renamed", "spelling"),
        "Gondia": ("Gondiya", "renamed", "spelling"),
        "Mumbai": ("Mumbai", "same", "no plan for this district; almost no crop data"),
        "Mumbai Suburban": ("Mumbai Suburban", "same", "no plan for this district; almost no crop data"),
        "Palghar": ("Thane", "split", "formed 2014 from Thane; plan for Palghar is the Thane plan"),
        "Raigad": ("Raigarh", "renamed", "spelling on the DataMeet map"),
    },
    "Telangana": {
        "Hyderabad": ("Hyderabad", "same", "no plan for this district; crop data only 1997-2000"),
        "Ranga Reddy": ("Rangareddy", "renamed", "spelling; after 2016 also has Shadnagar area from Mahbubnagar"),
        "Mahabubnagar": ("Mahbubnagar", "renamed", "spelling"),
        # 2016 reorganisation
        "Kumuram Bheem Asifabad": ("Adilabad", "split", ""),
        "Mancherial": ("Adilabad", "split", ""),
        "Nirmal": ("Adilabad", "split", ""),
        "Kamareddy": ("Nizamabad", "split", ""),
        "Jagitial": ("Karimnagar", "split", ""),
        "Peddapalli": ("Karimnagar", "split", ""),
        "Rajanna Sircilla": ("Karimnagar", "split", ""),
        "Hanumakonda": ("Warangal", "mixed", "Warangal Urban until 2021; includes Huzurabad area from Karimnagar"),
        "Jayashankar Bhupalapally": ("Warangal", "mixed", "includes Mahadevpur/Kataram area from Karimnagar"),
        "Mulugu": ("Warangal", "split", "formed 2019 from Jayashankar Bhupalapally"),
        "Jangoan": ("Warangal", "mixed", "includes a few mandals from Nalgonda"),
        "Mahabubabad": ("Warangal", "mixed", "includes Garla/Bayyaram area from Khammam"),
        "Bhadradri Kothagudem": ("Khammam", "split", ""),
        "Sangareddy": ("Medak", "split", ""),
        "Siddipet": ("Medak", "mixed", "includes Husnabad area from Karimnagar and Cheriyal area from Warangal"),
        "Medchal Malkajgiri": ("Rangareddy", "split", ""),
        "Vikarabad": ("Rangareddy", "mixed", "includes Kodangal area from Mahbubnagar"),
        "Nagarkurnool": ("Mahbubnagar", "split", ""),
        "Wanaparthy": ("Mahbubnagar", "split", ""),
        "Jogulamba Gadwal": ("Mahbubnagar", "split", ""),
        "Narayanpet": ("Mahbubnagar", "split", "formed 2019 from Mahabubnagar"),
        "Suryapet": ("Nalgonda", "split", ""),
        "Yadadri Bhuvanagiri": ("Nalgonda", "split", ""),
    },
    "Rajasthan": {
        "Chittorgarh": ("Chittaurgarh", "renamed", "spelling"),
        "Dholpur": ("Dhaulpur", "renamed", "spelling"),
        "Jalore": ("Jalor", "renamed", "spelling"),
        "Jhunjhunu": ("Jhunjhunun", "renamed", "spelling"),
    },
}

# 2011 districts that were carved out before 2011 -> the group to add up for 1997-2023 series
SERIES_GROUPS = {
    ("Karnataka", "Kolar"): "Kolar+Chikkaballapura",
    ("Karnataka", "Chikkaballapura"): "Kolar+Chikkaballapura",
    ("Karnataka", "Bangalore Rural"): "Bangalore Rural+Ramanagara",
    ("Karnataka", "Ramanagara"): "Bangalore Rural+Ramanagara",
    ("Karnataka", "Gulbarga"): "Gulbarga+Yadgir",
    ("Karnataka", "Yadgir"): "Gulbarga+Yadgir",
    ("Rajasthan", "Chittaurgarh"): "Chittaurgarh+Udaipur+Banswara+Pratapgarh",
    ("Rajasthan", "Udaipur"): "Chittaurgarh+Udaipur+Banswara+Pratapgarh",
    ("Rajasthan", "Banswara"): "Chittaurgarh+Udaipur+Banswara+Pratapgarh",
    ("Rajasthan", "Pratapgarh"): "Chittaurgarh+Udaipur+Banswara+Pratapgarh",
}


def read_dbf(path):
    """Minimal .dbf reader (avoids needing geopandas just for this)."""
    with open(path, "rb") as f:
        n, header_len, rec_len = struct.unpack("<IHH", f.read(12)[4:12])
        f.seek(32)
        fields = []
        while (d := f.read(32))[0] != 0x0D:
            fields.append((d[:11].split(b"\0")[0].decode(), d[16]))
        f.seek(header_len)
        rows = []
        for _ in range(n):
            raw, pos, row = f.read(rec_len)[1:], 0, {}
            for name, length in fields:
                row[name] = raw[pos:pos + length].decode("latin1").strip()
                pos += length
            rows.append(row)
    return rows


map_rows = read_dbf(MAP_DBF)
# On the 2011 map Telangana districts are under "Andhra Pradesh"
map_state = {s: ("Andhra Pradesh" if s == "Telangana" else s) for s in STATES}
census_code = {(r["ST_NM"], r["DISTRICT"]): r["censuscode"] for r in map_rows}

with open(LINKS, newline="", encoding="utf-8") as f:
    plan_of = {}  # a 2011 district can have two plans (Thane and Palghar), so join them with "; "
    for r in csv.DictReader(f):
        key = (r["state"], r["map_district_2011"])
        plan_of[key] = "; ".join(filter(None, [plan_of.get(key), r["district"]]))

crop_districts = set()
with open(CROPS, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["state_name"] in STATES:
            crop_districts.add((r["state_name"], r["district_name"], r["district_code"]))

out, problems = [], []
for state, name, code in sorted(crop_districts):
    map_name, relation, note = MAPPING[state].get(name, (name, "same", ""))
    cc = census_code.get((map_state[state], map_name))
    if cc is None:
        problems.append(f"{state} {name} -> {map_name}: not on the 2011 map")
    out.append({
        "state": state, "crop_district": name, "crop_district_code": code,
        "map_district_2011": map_name, "census_code_2011": cc or "",
        "plan_district": plan_of.get((state, map_name), ""),
        "relation": relation,
        "series_group": SERIES_GROUPS.get((state, map_name), map_name),
        "note": note,
    })

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)

# Checks: every plan district must receive crop data, and every crop district must be on the map
covered = {(r["state"], r["map_district_2011"]) for r in out}
for key, plan in plan_of.items():
    if key[0] in STATES and key not in covered:
        problems.append(f"plan {key[0]} {plan} ({key[1]}) gets no crop data")
print(f"wrote {OUT}: {len(out)} crop districts")
for state in STATES:
    rows = [r for r in out if r["state"] == state]
    counts = {k: sum(r["relation"] == k for r in rows) for k in ("same", "renamed", "split", "mixed")}
    print(f"  {state}: {len(rows)} -> {len({r['map_district_2011'] for r in rows})} districts of 2011, {counts}")
print("problems:", problems or "none")
