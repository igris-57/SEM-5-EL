"""Checks run on every claim before it is stored: quote check and number check."""
import re
import unicodedata

from .dates import parse_point, parse_range
from .schema import Claim

_TRANS = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", "\xa0": " ",
})
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "ten": 10, "fifteen": 15, "twenty": 20}
NUMBER_FIELDS = ["value", "delay_weeks", "dry_spell_min_days", "dry_spell_max_days"]


def norm(text):
    """Unicode-normalise and collapse all whitespace to single spaces."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANS)
    return re.sub(r"\s+", " ", text).strip()


def quote_match(fragment, page_text):
    """'exact' if the fragment is on the page (whitespace collapsed), 'loose' if it is
    there once all whitespace is removed (PDF text splits words: 't o', '33. 0'), else None."""
    f, p = norm(fragment), norm(page_text)
    if not f:
        return None
    if f in p:
        return "exact"
    if f.replace(" ", "") in p.replace(" ", ""):
        return "loose"
    return None


def numbers_in(text):
    t = norm(text).lower()
    t = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", t)     # "33. 0" -> "33.0"
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)        # "1,234" -> "1234"
    nums = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)}
    nums |= {float(v) for w, v in ORDINALS.items() if re.search(rf"\b{w}\b", t)}
    return nums


def date_problems(claim: Claim):
    """The claim's start/end (month, week) must be what its quote says, read by dates.py."""
    if claim.start_month is None and claim.end_month is None:
        return []
    start = (claim.start_month, claim.start_week) if claim.start_week else None
    end = (claim.end_month, claim.end_week) if claim.end_month and claim.end_week else None
    texts = claim.quote_parts + [" ".join(claim.quote_parts)]
    points = {p for t in texts if (p := parse_point(t))}
    ranges = {r for t in texts if (r := parse_range(t))}
    starts = points | {r[0] for r in ranges}
    ends = {r[1] for r in ranges} | points
    months = {m for m, _ in starts | ends}
    out = []
    if start and start not in starts:
        out.append(f"start {start} not what the quote says ({sorted(starts) or 'no date'})")
    elif not start and claim.start_month and claim.start_month not in months:
        out.append(f"start_month={claim.start_month} not in quote")
    if end and end not in ends:
        out.append(f"end {end} not what the quote says ({sorted(ends) or 'no date'})")
    return out


def check_claim(claim: Claim, page_text):
    """Return (problems, match). problems is a list of strings; empty means the claim passes."""
    problems, matches = [], []
    for frag in claim.quote_parts:
        m = quote_match(frag, page_text)
        if m is None:
            problems.append(f"quote not on page: {frag!r}")
        matches.append(m)

    quote = " ".join(claim.quote_parts)
    nums = numbers_in(quote)
    for f in NUMBER_FIELDS:
        v = getattr(claim, f)
        if v is not None and not any(abs(v - n) < 1e-6 for n in nums):
            problems.append(f"{f}={v:g} not in quote")
    problems += date_problems(claim)

    match = "loose" if "loose" in matches else "exact"
    return problems, match
