"""Read the plans' week/date phrases as (month, week-of-month).

Handles "1st Week of June", "Second week of November", "2nd fortnight of June",
"end of June", "last week of July", "15th June", "June 15", "24th MW (June 11-17)",
and ranges joined by "to" / "-" / "–" such as "1st July – 30th July",
"1st week to 4th week of November", "15th June to 15th July".
Week of month: days 1-7 -> 1, 8-14 -> 2, 15-21 -> 3, 22-31 -> 4 (5th weeks fold into 4).
"""
import re
from datetime import date, timedelta

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": 4, "fifth": 4, "end": 4}
_M = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_N = r"(\d{1,2})\s*(?:st|nd|rd|th)?"
_W = r"(first|second|third|fourth|fifth|last|\d)\s*(?:st|nd|rd|th)?"


def week_of_day(day):
    return min(4, (day - 1) // 7 + 1)


def _clean(s):
    s = s.lower().replace("–", "-").replace("—", "-")
    s = re.sub(r"(\d)\s+(st|nd|rd|th)\b", r"\1\2", s)          # "2 nd" -> "2nd"
    s = re.sub(r"\bt\s+o\b", "to", s)                         # "t o" -> "to"
    s = re.sub(r"\bfort\s+night", "fortnight", s)              # "fort night"
    s = re.sub(r"\boct\s+ober\b", "october", s)                # "Oct ober"
    s = re.sub(r"\b0ct\b", "oct", s)                          # zero for 'o': "0ct", "N0v"
    s = re.sub(r"\bn0v\b", "nov", s)
    s = re.sub(r"\biune\b", "june", s)                        # Tumkur "Iune 1st week"
    s = re.sub(r"\bof(?=(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))", "of ", s)  # "ofJanuary"
    s = re.sub(r"\b(?:weak|wee0k|wks?)\b", "week", s)          # "Last weak June", "July 2nd wk"
    s = re.sub(r"\bi\s*st\b", "1st", s)                       # "Ist week", "I st week"
    # Roman / abbreviated fortnights: "June IInd FN", "Ist FN" ("Ind FN" is ambiguous: left alone)
    s = re.sub(r"\b(?:ist|1st|first)\s*(?:fn|fortnight)\b", "1st fortnight", s)
    s = re.sub(r"\b(?:iind|2nd|second)\s*(?:fn|fortnight)\b", "2nd fortnight", s)
    s = re.sub(r"(st|nd|rd|th)(week|fortnight)", r"\1 \2", s)  # "2ndweek"
    return re.sub(r"\s+", " ", s).strip()


def _wk(tok):
    return WORDS.get(tok) or min(4, int(tok))


def _mw(m, **_):  # standard meteorological week n starts on day (n-1)*7+1 of the year
    d = date(2011, 1, 1) + timedelta(days=(int(m.group(1)) - 1) * 7)
    return d.month, week_of_day(d.day)


def _fortnight(m, is_end=False, **_):
    f = 1 if m.group(1) in ("1", "first") else 2
    return MONTHS[m.group(2)], (2 * f if is_end else 2 * f - 1)


def _end_mid(m, **_):
    return MONTHS[m.group(2)], 2 if m.group(1) in ("mid", "middle") else 4


def _week(m, default_month=None, **_):
    month = MONTHS[m.group(2)] if m.group(2) else default_month
    return (month, _wk(m.group(1))) if month else None


def _day_month(m, **_):
    return (MONTHS[m.group(2)], week_of_day(int(m.group(1)))) if int(m.group(1)) <= 31 else None


def _month_day(m, **_):
    return (MONTHS[m.group(1)], week_of_day(int(m.group(2)))) if int(m.group(2)) <= 31 else None


def _bare_day(m, default_month=None, **_):
    return (default_month, week_of_day(int(m.group(1)))) if default_month and int(m.group(1)) <= 31 else None


PATTERNS = [
    (rf"(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*(?:smw|mw|met\.? week|meteorological week)", _mw),
    (rf"{_W} fortnight(?: of)? {_M}", _fortnight),
    (rf"{_M}\s*,?\s*{_W} fortnight", lambda m, is_end=False, **_: (
        MONTHS[m.group(1)], (2 if m.group(2) in ("1", "first") else 4) if is_end
        else (1 if m.group(2) in ("1", "first") else 3))),
    (rf"\b(end|last week|mid|middle)(?: of)? {_M}", _end_mid),
    (rf"{_M}\s*end\b", lambda m, **_: (MONTHS[m.group(1)], 4)),         # "July end"
    (rf"{_M}\s*,?\s*{_W} week\b", lambda m, **_: (MONTHS[m.group(1)], _wk(m.group(2)))),
    (rf"{_W} week\b(?: of)?(?: {_M})?", _week),
    # a span of days "11th-20th June" starts at the first day (ends at the second)
    (rf"{_M}\s*{_N}\s*(?:-|to)\s*{_N}\b", lambda m, is_end=False, **_: (    # "Oct. 15-25"
        (MONTHS[m.group(1)], week_of_day(int(m.group(3 if is_end else 2))))
        if max(int(m.group(2)), int(m.group(3))) <= 31 else None)),
    (rf"\b{_N}\s*(?:-|to)\s*{_N}\s*(?:of\s+)?{_M}", lambda m, is_end=False, **_: (
        (MONTHS[m.group(3)], week_of_day(int(m.group(2 if is_end else 1))))
        if max(int(m.group(1)), int(m.group(2))) <= 31 else None)),
    (rf"\b{_N}\s*(?:of\s+)?{_M}", _day_month),                          # "15th June", "1st of June"
    (rf"{_M}\s*{_N}\b", _month_day),
    (rf"^{_N}$", _bare_day),
]


def parse_point(s, default_month=None, is_end=False):
    """(month, week) of the first date phrase in s, or None. 'Delay by 8 week' is a length of
    time, not a date, so it is skipped ('Delay by 8 week Aug 2nd week' -> (8, 2))."""
    s = re.sub(r"delay(?:ed)?\s*(?:by|of)?\s*\d+\s*weeks?", " ", _clean(s))
    hits = []
    for order, (pat, fn) in enumerate(PATTERNS):
        for m in re.finditer(pat, s):
            v = fn(m, default_month=default_month, is_end=is_end)
            if v:
                hits.append((m.start(), order, v))  # earliest match; ties go to the earlier pattern
                break
    return min(hits)[2] if hits else None


def _month_in(s):
    m = re.search(_M, _clean(s))
    return MONTHS[m.group(1)] if m else None


def _bare_month(s):
    """Month number if s is only a month name ('June', 'august)'), else None."""
    m = re.fullmatch(rf"\s*{_M}\s*[).,;]*\s*", s)
    return MONTHS[m.group(1)] if m else None


def parse_range(s):
    """((m1, w1), (m2, w2)) for a sowing-window phrase, or None.
    A single fortnight/week/month gives its own start and end; "June to August" gives
    (6, 1) to (8, 4)."""
    c = _clean(s)
    c = re.sub(r"\(.*?\)", " ", c) if "mw" not in c else c   # drop "(Mustard)" notes
    parts = re.split(r"\s+to\s+|\s*-\s*(?=\D)|\s+-\s+|(?<=[a-z.])\s*-\s*(?=\d)", c, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        a, b = parts
        ma, mb = _bare_month(a), _bare_month(b)
        if ma and mb:
            return (ma, 1), (mb, 4)
        end_m = _month_in(b)
        if _month_in(a) is None and end_m and "fortnight" in a:
            a = f"{a} {list(MONTHS)[end_m - 1]}"  # "1st fortnight to 2nd fortnight October"
        start = parse_point(a, default_month=end_m) or parse_point(a, default_month=_month_in(a)) \
            or ((ma, 1) if ma else None)                    # "June to July last week"
        end = parse_point(b, default_month=_month_in(a), is_end=True) or ((mb, 4) if mb else None)
        if start and end and end_m is None and end <= start:
            return None  # "2nd June to Ist week": the end's month is missing, do not guess it
        if (start and _month_in(a) and start[0] != _month_in(a)) or (end and end_m and end[0] != end_m):
            return None  # a side names a month but was read as another one: the text is garbled
        if start and end:
            return start, end
        if re.search(r"\bto\b", c):
            return None  # a range with one side we cannot read: never guess from the other side
    p = parse_point(c)
    if p:
        # a fortnight or a day span ('1-15 Oct') has its own end; a single week ends where it starts
        return p, parse_point(c, is_end=True) or p
    m = _month_in(c)
    if m and re.fullmatch(rf"{_M}", c.strip()):
        return (m, 1), (m, 4)
    return None
