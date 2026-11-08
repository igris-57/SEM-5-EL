# Monsoon Plan Checker

Checks India's district agriculture contingency plans (ICAR-CRIDA, 105 plans in Karnataka,
Maharashtra, Rajasthan and Telangana) against IMD rainfall and crop statistics.

This repo has **code only**. All data (plans, IMD rain, crop data, extracted claims, review
sheets) is on Google Drive: copy the Drive folder's contents into this folder, keeping the
same paths (setup steps in the Drive folder's `README.txt`). `.gitignore` keeps data out of git.

| Folder | What | Owner |
|---|---|---|
| `p3/` | Plan text, claim extractor, plan figures, planted errors, hand-off files, report Introduction + Related Work. Start with [p3/STATUS.md](p3/STATUS.md) | Person 3 |
| `DOCS/data/Main EL/` | Scripts that download the raw data (`download_data.py`, `download_temperature.py`) and build the district crosswalk | data |

Person 3 setup and checks:

```
pip install pymupdf pydantic pandas openpyxl pytest
pip install google-genai           # only for the optional Gemini extractor / comparison
python -m pytest p3/tests          # needs the Drive data in place
```
