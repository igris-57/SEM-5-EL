"""
Downloads the data for: "Are India's monsoon contingency plans still right?"

Run on your own laptop, with contingency_plan_links.csv in the same folder:
    pip install requests
    python download_data.py

Everything is saved in a folder called "data" (roughly 1-1.5 GB). Safe to re-run: files you already have are skipped.
Anything that fails is listed in data/failed_downloads.txt:
  - a plan PDF: open its link in a browser and save it by hand
  - an IMD rainfall year: use the year form on https://imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html

One manual step: the best crop data (to 2024-25) needs a free Dataful account. The script prints the
4 links at the end; download each as CSV into data/crops/.
"""
import csv
import os
import time

import requests

OUT = "data"
LINKS_CSV = "contingency_plan_links.csv"

# States to download. These 4 give 105 plans. Add "Andhra Pradesh" for 12 more.
STATES = ["Karnataka", "Maharashtra", "Telangana", "Rajasthan"]

# IMD rainfall years: 1981-2010 = old normal, 2011-2025 = recent years.
RAIN_YEARS = range(1981, 2026)

HEADERS = {"User-Agent": "Mozilla/5.0"}  # some govt sites reject requests without a browser-like header
failed = []


def download(url, path, kind=None, form=None):
    """Save url to path (POST if form is given). Returns False if the file was already there."""
    if os.path.exists(path):
        print("already have", path)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    method = "POST" if form else "GET"
    with requests.request(method, url, data=form, headers=HEADERS, timeout=600, stream=True) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    with open(tmp, "rb") as f:
        head = f.read(1024)
    looks_right = {
        "pdf": b"%PDF" in head,
        "nc": head.startswith(b"CDF") or head.startswith(b"\x89HDF"),  # NetCDF 3 or NetCDF 4
        "csv": not head.lstrip().startswith(b"<"),  # an HTML error page starts with "<"
    }.get(kind, True)
    if not head or not looks_right:
        os.remove(tmp)
        raise ValueError(f"server did not send a {kind or 'proper'} file (probably an error page)")
    os.replace(tmp, path)  # only complete files get the real name
    print("saved", path)
    return True


def fetch(name, url, path, kind=None, form=None):
    """download() with one retry. Failures are collected for failed_downloads.txt."""
    for attempt in (1, 2):
        try:
            if download(url, path, kind, form):
                time.sleep(1)  # be polite to the server
            return
        except Exception as e:
            if attempt == 2:
                print("FAILED", name, "->", e)
                failed.append(f"{name} | {url}")
            elif isinstance(e, requests.exceptions.SSLError):
                url = url.replace("https://", "http://", 1)  # some govt sites have certificate problems
            else:
                time.sleep(5)


# 1) District Agriculture Contingency Plans (ICAR-CRIDA), links in contingency_plan_links.csv
with open(LINKS_CSV, newline="", encoding="utf-8") as f:
    plans = [row for row in csv.DictReader(f) if row["state"] in STATES]
print(f"{len(plans)} plans to get for: {', '.join(STATES)}")
for row in plans:
    path = f"{OUT}/plans/{row['state'].replace(' ', '_')}/{row['district'].replace(' ', '_')}.pdf"
    fetch(f"plan {row['state']} {row['district']}", row["url"], path, "pdf")

# 2) IMD daily gridded rainfall, 0.25 degree, NetCDF, one file per year (~24 MB each).
#    Open with xarray: variable RAINFALL (mm/day), dimensions TIME, LATITUDE, LONGITUDE; -999 = no data.
#    IMD asks you to cite Pai et al. (2014), MAUSAM 65(1), 1-18.
for year in RAIN_YEARS:
    fetch(f"IMD rainfall {year}", "https://imdpune.gov.in/cmpg/Griddata/RF25.php",
          f"{OUT}/imd/RF25_ind{year}_rfp25.nc", "nc", form={"RF25": str(year)})

# 3) District boundaries from Census 2011 = the same districts as the plans (DataMeet, CC BY 2.5 India).
#    Join on the map_district_2011 / census_code_2011 columns of contingency_plan_links.csv.
#    On this map Telangana districts are under "Andhra Pradesh", and Palghar is still inside Thane.
MAP = "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist"
for ext in ("shp", "shx", "dbf", "prj"):
    fetch(f"district map .{ext}", f"{MAP}.{ext}", f"{OUT}/map_2011/2011_Dist.{ext}")

# 4) District crop area & production (Ministry of Agriculture data)
#    a) Automatic backup: India Data Portal copy, 1997-2021. 2020 is under half complete and 2021 is
#       almost empty, so only use it up to 2019.
fetch("crop data (India Data Portal)",
      "https://ckandev.indiadataportal.com/dataset/80789131-1b7d-4809-a03e-7ce88cee2917/"
      "resource/ead44f5f-6471-48ec-a488-4b5894302aaa/download/crop-wise-area-production-yield.csv",
      f"{OUT}/crops/crop_apy_1997_2021.csv", "csv")

#    b) Manual, better: Dataful copies, 1997-98 to 2024-25, with LGD district codes.
#       Before use: drop the "State Total" rows, and add new districts back into their 2011 parent.
CROP_PAGES = {
    "Karnataka": "https://dataful.in/datasets/4561/",
    "Maharashtra": "https://dataful.in/datasets/5632/",
    "Telangana": "https://dataful.in/datasets/4426/",
    "Rajasthan": "https://dataful.in/datasets/4430/",
    "Andhra Pradesh": "https://dataful.in/datasets/4888/",
}

with open(f"{OUT}/failed_downloads.txt", "w", encoding="utf-8") as f:
    f.write("".join(line + "\n" for line in failed))
print(f"\nDone. {len(failed)} downloads failed (list in {OUT}/failed_downloads.txt).")
print("Manual step: sign up free at dataful.in, then download these as CSV into data/crops/:")
for state in STATES:
    print(f"  {state}: {CROP_PAGES[state]}")

# Optional: daily max/min temperature (1 degree grid) for the heat-wave parts of the plans:
#   pip install imdlib
#   import imdlib as imd
#   imd.get_data("tmax", 1981, 2022, fn_format="yearwise", file_dir="data/imd_temp")
