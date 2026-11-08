"""Person 3: DRAFT shared evaluation set (~300 claims) for all three systems.

Not frozen: the team still has to agree on the real/planted mix and on the decision-rule
questions in data/processed/README.md. Re-run with other numbers once that is settled.

Rules used here:
  - core districts only: the 5 pilots are for tuning (work split: "Tune only on pilot
    planted claims, never on core ones")
  - Palghar is left out: its 2016 plan repeats the Thane 2011 plan's figures
  - real claims: only claims with a decision rule and no open rule_note, spread evenly over
    rule types, then round-robin over states
  - planted claims: same filter, spread evenly over error types; one claim per planted error;
    a claim id is never in the set as both its real and its planted version
  - rows are shuffled before numbering, so the eval id does not reveal the source
  - fixed seed, so the same command gives the same set
  - eval_set_draft.csv has the answers (Person 5 only); eval_claims_draft.jsonl has the same
    claims without them (for the agents and the baseline)

Needs `python -m p3.export --all` first.

    python -m p3.evalset                        # 200 real + 100 planted
    python -m p3.evalset --real 150 --planted 150
"""
import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
OUT = DATA / "eval" / "eval_set_draft.csv"              # with answers: Person 5 only
BLIND = DATA / "eval" / "eval_claims_draft.jsonl"       # the same claims, no answers: agents
SEED = 2026
EXCLUDE_PLANS = {"Maharashtra/Palghar"}


def spread(groups, n, rng):
    """Take n items as evenly as possible across groups (dict of lists), round-robin."""
    pools = {k: rng.sample(v, len(v)) for k, v in sorted(groups.items())}
    taken = []
    while len(taken) < n and any(pools.values()):
        for k in list(pools):
            if pools[k] and len(taken) < n:
                taken.append(pools[k].pop())
    return taken


def main():
    from .claims.extract import PILOT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--real", type=int, default=200)
    ap.add_argument("--planted", type=int, default=100)
    a = ap.parse_args()
    rng = random.Random(SEED)
    skip = set(PILOT) | EXCLUDE_PLANS

    # planted first, so the real sample can avoid their claim ids: the agents must never see the
    # real and the planted version of the same claim side by side
    planted_by_id = {}
    for f in sorted((DATA / "claims_planted").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            planted_by_id[c["claim_id"]] = c
    by_error, seen = defaultdict(list), set()
    for row in csv.DictReader(open(DATA / "eval" / "planted_answers.csv", encoding="utf-8")):
        plan = row["plan_id"].replace("@planted", "")
        ids = row["planted_claim_id"]
        # same rule as the real claims (a rule, no open rule_note); the same crop planted twice on
        # one page lands on the same claims: keep one
        if plan not in skip and ids and ids not in seen:
            c = planted_by_id[ids.split(";")[0]]
            if c["rule_type"] and not c["rule_note"]:
                seen.add(ids)
                by_error[row["error_type"].split("_x")[0]].append(row)
    planted = spread(by_error, a.planted, rng)
    planted_ids = {i for row in planted for i in row["planted_claim_id"].split(";")}

    by_type = defaultdict(lambda: defaultdict(list))
    for f in sorted((DATA / "claims").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            if c["plan_id"] not in skip and c["rule_type"] and not c["rule_note"] \
                    and c["claim_id"] not in planted_ids:
                by_type[c["rule_type"]][c["state"]].append(c)
    per_type = a.real // len(by_type)
    real = []
    for i, (t, states) in enumerate(sorted(by_type.items())):
        n = per_type + (1 if i < a.real - per_type * len(by_type) else 0)
        real += spread(states, n, rng)

    items = [("real", c, None) for c in real] + \
        [("planted", planted_by_id[row["planted_claim_id"].split(";")[0]], row) for row in planted]
    rng.shuffle(items)  # eval ids must not reveal which claims are planted
    rows, blind = [], []
    for i, (source, c, row) in enumerate(items):
        eid = f"E{i + 1:03d}"
        rows.append({"eval_id": eid, "source": source, "census_code_2011": c["census_code_2011"],
                     "plan_id": c["plan_id"], "state": c["state"], "claim_id": c["claim_id"],
                     "claims_file": f"{'claims' if source == 'real' else 'claims_planted'}/"
                                    f"{c['census_code_2011']}.jsonl",
                     "rule_type": c["rule_type"], "claim_type": c["claim_type"],
                     "error_type": row["error_type"] if row else "",
                     "expected_label": row["expected_label"] if row else "",
                     "statement": c["statement"]})
        blind.append({"eval_id": eid, **c})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(BLIND, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(b, ensure_ascii=False) + "\n" for b in blind)
    print(f"{len(real)} real + {len(planted)} planted -> {OUT} (key, Person 5 only)\n"
          f"  same claims without answers -> {BLIND} (for the agents and the baseline)")


if __name__ == "__main__":
    main()
