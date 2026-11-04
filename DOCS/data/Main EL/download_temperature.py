"""
Downloads IMD daily max/min temperature (1 degree grid) for the heat-wave parts of the plans.

    pip install imdlib
    python download_temperature.py

Saved as data/imd_temp/tmax/<year>.GRD and data/imd_temp/tmin/<year>.GRD (~1.4 MB each).
Safe to re-run: years you already have are skipped. Failures go to data/imd_temp/failed_years.txt.
Open with:  imdlib.open_data("tmax", 1981, 2025, "yearwise", "data/imd_temp/tmax").get_xarray()
IMD asks you to cite Srivastava et al. (2009), Atmospheric Science Letters 10, 249-254.
"""
import os

import imdlib as imd

OUT = "data/imd_temp"
YEARS = range(1981, 2026)
failed = []

for var in ("tmax", "tmin"):
    folder = f"{OUT}/{var}"
    os.makedirs(folder, exist_ok=True)
    for year in YEARS:
        if os.path.exists(f"{folder}/{year}.GRD"):
            print("already have", var, year)
            continue
        try:
            imd.get_data(var, year, year, fn_format="yearwise", file_dir=OUT)  # saves to OUT/<var>/<year>.GRD
            if not os.path.exists(f"{folder}/{year}.GRD"):
                raise FileNotFoundError("imdlib reported no error but saved no file")
        except Exception as e:
            print("FAILED", var, year, "->", e)
            failed.append(f"{var} {year}")

with open(f"{OUT}/failed_years.txt", "w", encoding="utf-8") as f:
    f.write("".join(line + "\n" for line in failed))
print(f"\nDone. {len(failed)} years failed (list in {OUT}/failed_years.txt).")
