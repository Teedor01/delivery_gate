from __future__ import annotations

import re
from datetime import date
from typing import List, Tuple

_MONTHS = {m: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may", "may"), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")], start=1) for m in names}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MDY_NAME = re.compile(_MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
_DMY_NAME = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"\.?,?\s+(\d{4})\b", re.I)
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp][Mm])?(?!\d)")


def _valid(y: int, m: int, d: int):
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> Tuple[List[str], List[str]]:
    """Returns (resolved ISO dates, ambiguous numeric date strings)."""
    found: List[str] = []
    ambiguous: List[str] = []
    for y, m, d in _ISO.findall(text):
        iso = _valid(int(y), int(m), int(d))
        if iso:
            found.append(iso)
    for mon, d, y in _MDY_NAME.findall(text):
        iso = _valid(int(y), _MONTHS[mon.lower()], int(d))
        if iso:
            found.append(iso)
    for d, mon, y in _DMY_NAME.findall(text):
        iso = _valid(int(y), _MONTHS[mon.lower()], int(d))
        if iso:
            found.append(iso)
    for a, b, y in _NUMERIC.findall(text):
        a_i, b_i = int(a), int(b)
        if a_i <= 12 and b_i > 12:
            iso = _valid(int(y), a_i, b_i)
        elif a_i > 12 and b_i <= 12:
            iso = _valid(int(y), b_i, a_i)
        elif a_i == b_i and a_i <= 12:
            iso = _valid(int(y), a_i, b_i)
        else:
            ambiguous.append(f"{a}/{b}/{y}")
            continue
        if iso:
            found.append(iso)
    return found, ambiguous


def find_times(text: str) -> List[str]:
    out: List[str] = []
    for h, m, ap in _TIME.findall(text):
        h_i, m_i = int(h), int(m)
        if m_i > 59:
            continue
        if ap:
            if not 1 <= h_i <= 12:
                continue
            h_i = (h_i % 12) + (12 if ap.lower() == "pm" else 0)
        elif h_i > 23:
            continue
        out.append(f"{h_i:02d}:{m_i:02d}")
    return out
