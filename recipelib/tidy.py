"""Tidy how recipes read without changing what they are.

Old recipe collections are full of titles typed in capitals ("PEPPERY RICE"). tidy_title turns
those into ordinary title case ("Peppery Rice") and leaves every other title exactly as it is,
so a title someone capitalised on purpose ("BBQ Ribs", "Coq au Vin") is not touched.
"""
from __future__ import annotations

import re

_SMALL = {"a", "an", "and", "as", "at", "au", "aux", "by", "con", "de", "del", "di", "du", "en", "et", "for",
          "from", "in", "la", "le", "of", "on", "or", "the", "to", "with", "without", "y"}
_KEEP = {"BBQ", "ABM", "TVP", "USA", "UK", "II", "III", "IV", "VI", "VII", "VIII", "MSG", "BLT", "PB",
         "KFC", "TV", "OJ", "XO", "FF"}
_WORD = re.compile(r"[A-Za-zÀ-ÿ]+(?:['’][A-Za-zÀ-ÿ]+)*")


def _cap(word: str) -> str:
    parts = re.split(r"(['’])", word.lower())
    out = [parts[0][:1].upper() + parts[0][1:]]
    for n in range(1, len(parts), 2):
        tail = parts[n + 1]
        # O'Brien, D'Oeuvres, L'Orange: a one-letter start means the next part is the real word
        out.append(parts[n] + (tail[:1].upper() + tail[1:] if len(parts[0]) == 1 and len(tail) > 2 else tail))
    return "".join(out)


def tidy_title(title: str) -> str:
    """'PEPPERY RICE (QUICK)' -> 'Peppery Rice (Quick)'. Titles that are not all capitals are returned unchanged."""
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 4 or any(c.islower() for c in letters):
        return title
    first = True

    def fix(m: "re.Match") -> str:
        nonlocal first
        word = m.group(0)
        start_of_part = first or title[:m.start()].rstrip()[-1:] in "(:-/–—"
        first = False
        if word in _KEEP:
            return word
        if word.lower() in _SMALL and not start_of_part:
            return word.lower()
        return _cap(word)

    return _WORD.sub(fix, title)
