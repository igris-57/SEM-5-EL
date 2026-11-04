"""Person 3, Task 2: Claim Extractor.

One Gemini call per page of plan_text/, Pydantic check per claim, word-for-word quote
check and number check; pages with problems get one retry with the problems listed.

    python -m p3.claims.extract --pilot
    python -m p3.claims.extract --plans Karnataka/Udupi Rajasthan/Jodhpur
    python -m p3.claims.extract --all            # skips plans already done; --force redoes

Writes claims/<State>/<District>.jsonl (accepted), claims/_rejected/... (with reasons)
and appends one row per page to claims/run_log.csv.
"""
import argparse
import csv
import json
from pathlib import Path

from pydantic import ValidationError

from .checks import check_claim
from .prompt import PROMPT_VERSION, SYSTEM, page_prompt, retry_prompt
from .schema import Claim, PageClaims, StoredClaim

ROOT = Path(__file__).resolve().parents[2]
PLAN_TEXT = ROOT / "plan_text"
OUT = ROOT / "claims"

# Pilot set = the five districts Person 1 loaded into PostgreSQL (4 Nov 2026), by plan file name:
# Chamarajanagar, Chitradurga, Kalaburagi (plan: Gulbarga), Shivamogga (Shimoga), Tumakuru (Tumkur)
PILOT = ["Karnataka/Chamarajanagar", "Karnataka/Chitradurga", "Karnataka/Gulbarga",
         "Karnataka/Shimoga", "Karnataka/Tumkur"]

LOG_FIELDS = ["plan_id", "page", "n_claims", "n_rejected", "retried", "in_tokens",
              "out_tokens", "seconds", "cached", "model", "prompt_version", "error"]


def parse(text, page_text):
    """Split an LLM answer into (accepted [(Claim, match)], rejected [(raw, problems)])."""
    try:
        raw_claims = json.loads(text).get("claims", [])
    except (json.JSONDecodeError, AttributeError) as e:
        return [], [({"raw": text[:500]}, [f"bad JSON: {e}"])]
    ok, bad = [], []
    for raw in raw_claims:
        try:
            c = Claim.model_validate(raw)
        except ValidationError as e:
            bad.append((raw, [err["msg"] for err in e.errors()]))
            continue
        problems, match = check_claim(c, page_text)
        if problems:
            bad.append((raw, problems))
        else:
            ok.append((c, match))
    return ok, bad


def extract_page(llm, plan, page, prev_text):
    base = page_prompt(plan, page, prev_text)
    text, usage = llm.generate_json(SYSTEM, base, PageClaims)
    ok, bad = parse(text, page["text"])
    retried = False
    if bad:
        retried = True
        problems = [f"{r.get('statement', r)}: {'; '.join(p)}" for r, p in bad]
        text, u2 = llm.generate_json(SYSTEM, retry_prompt(base, problems), PageClaims)
        ok, bad = parse(text, page["text"])
        for k in ("in_tokens", "out_tokens", "seconds"):
            usage[k] = usage.get(k, 0) + u2.get(k, 0)
        usage["cached"] = usage["cached"] and u2["cached"]
    return ok, bad, retried, usage


def extract_plan(llm, plan_id, force=False):
    out = OUT / f"{plan_id}.jsonl"
    if out.exists() and not force:
        print(f"skip {plan_id} (done)")
        return
    plan = json.loads((PLAN_TEXT / f"{plan_id}.json").read_text(encoding="utf-8"))
    accepted, rejected, log = [], [], []
    prev = ""
    for page in plan["pages"]:
        if page["low_text"]:
            prev = page["text"]
            continue
        row = {"plan_id": plan_id, "page": page["page"], "model": llm.model,
               "prompt_version": PROMPT_VERSION, "error": ""}
        try:
            ok, bad, retried, usage = extract_page(llm, plan, page, prev)
        except Exception as e:  # keep going; the page is logged and can be re-run
            ok, bad, retried, usage = [], [], False, {}
            row["error"] = f"{type(e).__name__}: {e}"[:300]
        for c, match in ok:
            accepted.append(StoredClaim(
                **c.model_dump(), claim_id=f"{plan_id}#p{page['page']}#c{len(accepted) + 1}",
                plan_id=plan_id, state=plan["state"], district=plan["district"],
                census_code_2011=plan.get("census_code_2011"), page=page["page"],
                quote_match=match, model=llm.model, prompt_version=PROMPT_VERSION))
        for raw, problems in bad:
            rejected.append({"plan_id": plan_id, "page": page["page"],
                             "problems": problems, "claim": raw})
        row.update(n_claims=len(ok), n_rejected=len(bad), retried=retried, **usage)
        log.append(row)
        print(f"{plan_id} p{page['page']}: {len(ok)} ok, {len(bad)} rejected"
              f"{' (retried)' if retried else ''}{' ERROR ' + row['error'] if row['error'] else ''}")
        prev = page["text"]

    write_jsonl(OUT / "_rejected" / f"{plan_id}.jsonl", rejected)
    append_log(log)
    if any(r["error"] for r in log):
        print(f"{plan_id}: some pages failed; not marking plan as done")
        write_jsonl(OUT / "_partial" / f"{plan_id}.jsonl", [c.model_dump() for c in accepted])
        return
    write_jsonl(out, [c.model_dump() for c in accepted])
    print(f"{plan_id}: {len(accepted)} claims, {len(rejected)} rejected -> {out}")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def append_log(rows):
    path = OUT / "run_log.csv"
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plans", nargs="+", help="plan ids like Karnataka/Udupi")
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--rpm", type=float, default=10, help="max requests per minute")
    ap.add_argument("--force", action="store_true", help="redo plans already extracted")
    a = ap.parse_args()

    from .gemini import GeminiLLM
    llm = GeminiLLM(model=a.model, rpm=a.rpm, cache_dir=OUT / "_cache")
    if a.all:
        plans = sorted(p.relative_to(PLAN_TEXT).with_suffix("").as_posix()
                       for p in PLAN_TEXT.glob("*/*.json"))
    else:
        plans = PILOT if a.pilot else a.plans
    for pid in plans:
        extract_plan(llm, pid, force=a.force)


if __name__ == "__main__":
    main()
