"""MealMaster (.mmf / .txt) recipe parser.

MealMaster files hold one or more recipes. Each recipe looks like:

    MMMMM----- Recipe via Meal-Master (tm) v8.05
          Title: Chocolate Chip Cookies
     Categories: Cookies, Desserts
          Yield: 48 cookies

        2 1/4 c  Flour
          1 ts   Baking soda
    MMMMM---------------TOPPING---------------      <- optional ingredient group
          1 c    Pecans, chopped
               -- toasted                          <- continuation of previous line

      Mix and bake at 375 for 10 minutes.
    MMMMM                                           <- end marker

Ingredient lines use fixed columns: 7-char amount, space, 2-char unit, space,
item text. Two ingredients can share one line (second column near col 40).
Plenty of files in the wild are sloppy, so there is a free-form fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import List, Optional, Tuple

from .models import Ingredient, Recipe
from .units import canonical_unit, format_plain, parse_quantity

_START_RE = re.compile(r"^(?:m{5}|-{5,}).*meal[\s-]?master", re.IGNORECASE)
_FIELD_RE = re.compile(r"^\s*(title|categories|yield|servings)\s*:\s*(.*?)\s*$", re.IGNORECASE)
_QTY_REGION_RE = re.compile(r"^[\d\s/.]*$")
_UNIT_REGION_RE = re.compile(r"^[A-Za-z]{0,2}$")
_FREEFORM_RE = re.compile(r"^\s*((?:\d+\s+)?\d+/\d+|\d*\.\d+|\d+)\s+(\S+)\s+(.+?)\s*$")
_YIELD_RE = re.compile(r"^((?:\d+\s+)?\d+/\d+|\d*\.\d+|\d+)\s*(.*)$")
_STEP_RE = re.compile(r"^\s*\d+[.)]\s")


@dataclass
class ParseResult:
    recipes: List[Recipe] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- public API

def parse_file(path) -> ParseResult:
    return parse_text(decode_bytes(Path(path).read_bytes()))


# Characters that are common in real recipe text. Anything else outside ASCII counts against a guess.
_FRACTION_CHARS = "\u00bd\u00bc\u00be"            # 1/2 1/4 3/4
_QUOTE_CHARS = "\u2018\u2019\u201c\u201d\u2013\u2014\u2026"
# Windows-1252 characters that hardly ever appear in recipes (their DOS readings are accented letters).
_WINDOWS_ODDITIES = "\u20ac\u201a\u0192\u201e\u2020\u2021\u02c6\u2030\u0160\u2039\u0152\u017d\u02dc\u2122\u0161\u203a\u0153\u017e\u0178"
_HIGH_RE = re.compile(r"[^\x00-\x7f]+")


def _plausibility(text: str) -> int:
    """Score how much the non-ASCII characters of a decoded file look like recipe text.

    Old MealMaster files are DOS text (code page 437); newer ones are Windows-1252. The same byte
    is a degree sign in one and a Scandinavian letter in the other, so the guess is made from
    context: degree signs and fractions sit next to digits, accented letters sit inside words,
    and rules are long runs of one line-drawing character.
    """
    score = 0
    for m in _HIGH_RE.finditer(text):
        run = m.group(0)
        before = text[m.start() - 1] if m.start() else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if len(run) >= 2 and len(set(run)) == 1:
            if "\u2500" <= run[0] <= "\u257f":
                score += len(run)       # a rule drawn with one line-drawing character
            elif run[0] != "\u00a0":
                score -= len(run)       # the same accented letter repeated is not a word
            continue
        for i, ch in enumerate(run):
            prev = run[i - 1] if i else before
            nxt = run[i + 1] if i + 1 < len(run) else after
            in_word = (prev.isalpha() and prev != ch) or (nxt.isalpha() and nxt != ch)
            if ch == "\u00b0":
                score += 2 if (prev.isdigit() or nxt in "FCfc") else 0
            elif ch in _FRACTION_CHARS:
                score += 2 if (prev.isdigit() or prev.isspace() or nxt.isspace()) else 0
            elif ch == "\u00a0":
                pass
            elif ch == "\u2026":
                score += 1 if prev.isalpha() else 0
            elif ch in _QUOTE_CHARS:
                score += 1
            elif ch in _WINDOWS_ODDITIES:
                score -= 1
            elif ch in "\u00ff\u00fe\u00f8\u00d8" and not (prev.isalpha() and nxt.isalpha()):
                score -= 2      # y-umlaut, thorn, o-slash on their own: almost always a misread
            elif ch.isalpha() and ord(ch) < 0x250:
                score += 1 if in_word else 0
            else:
                score -= 1      # Greek, maths, stray box-drawing, control characters
    return score


def decode_bytes(data: bytes) -> str:
    """Decode a recipe file: UTF-8 if valid, otherwise whichever of DOS (cp437) and Windows-1252
    makes the accented characters, degree signs and fractions read like recipe text."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    windows = _decode_windows(data)
    dos = data.decode("cp437")
    # MealMaster was a DOS program, so DOS wins when the two readings are equally plausible.
    file_is_dos = _plausibility(dos) >= _plausibility(windows)
    # Collections stitched together from several sources mix both, so each line gets its own
    # vote and only undecided lines follow the file as a whole.
    out = []
    for d, w in zip(dos.split("\n"), windows.split("\n")):
        if d == w:
            out.append(d)
            continue
        ds, ws = _plausibility(d), _plausibility(w)
        out.append(d if ds > ws or (ds == ws and file_is_dos) else w)
    return "\n".join(out).replace("\u00a0", " ")


def _decode_windows(data: bytes) -> str:
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_text(text: str) -> ParseResult:
    result = ParseResult()
    for block in _split_blocks(text.expandtabs(8)):
        recipe, warnings = _parse_block(block)
        result.warnings.extend(warnings)
        if recipe is not None:
            result.recipes.append(recipe)
    return result


# ----------------------------------------------------------- block splitting

def _is_end_marker(line: str) -> bool:
    s = line.rstrip()
    if re.fullmatch(r"-{5}", s):
        return True
    return bool(re.match(r"^m{5}", s, re.IGNORECASE)) and not _group_name(s)


def _group_name(line: str) -> str:
    """Name from 'MMMMM-----SAUCE-----' or '-------SAUCE-------' lines, else ''."""
    s = line.rstrip()
    if re.match(r"^m{5}", s, re.IGNORECASE):
        name = s[5:].strip("- \t")
    else:
        t = s.strip()
        if not re.fullmatch(r"-{3,}\s*[^-\s](?:.*?[^-\s])?\s*-{3,}", t):
            return ""
        name = t.strip("- \t")
    return name.rstrip(":").strip()


def _split_blocks(text: str) -> List[List[str]]:
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in text.splitlines():
        if _START_RE.match(line):
            if current is not None:  # missing end marker: close previous recipe
                blocks.append(current)
            current = []
        elif current is not None and _is_end_marker(line):
            blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)
    return blocks


# ----------------------------------------------------------- ingredient lines

def _strict_parts(line: str) -> Optional[Tuple[str, str, str]]:
    """Fixed-width MealMaster ingredient line -> (qty, unit, item), else None."""
    padded = line.ljust(11)
    qty, unit = padded[0:7], padded[8:10].strip()
    if padded[7] != " " or padded[10] != " ":
        return None
    if not _QTY_REGION_RE.match(qty) or not _UNIT_REGION_RE.match(unit):
        return None
    item = line[11:].strip()
    if not item:
        return None
    return qty.strip(), unit, item


RIGHT_COL = 41  # right-hand ingredient: qty [41:48], unit [49:51], item from 52


def _split_two_columns(line: str):
    """If a line holds a second, right-hand ingredient return (left, right, False).

    The right-hand field uses the same layout as the left, shifted by 41 columns. Wrapped text
    in either column is marked with a leading '-' (see _join_continuation); a right-hand field
    with no amount or unit but no dash is a new ingredient such as "Watercress for garnish".
    """
    if len(line) <= RIGHT_COL + 11:
        return None
    left, right = line[:RIGHT_COL], line[RIGHT_COL:]
    if left[-1] != " ":
        return None
    left_ok = _strict_parts(left.rstrip()) is not None
    if not left_ok and left.strip():
        return None
    parts = _strict_parts(right)
    if parts is None:
        return None
    return left.rstrip(), right.rstrip(), False


ITEM_WIDTH = 28  # MealMaster's item field; longer items are wrapped onto '-' lines

# Words that are complete on their own, so text wrapped after one of them starts a new word.
_WHOLE_WORDS = {"and", "or", "if", "of", "the", "with", "for", "inch", "a", "&"}


def _join_continuation(base: str, cont: str, base_width: int = 0) -> str:
    """Append wrapped text to an ingredient.

    MealMaster wraps long items onto lines that begin with '-' in the item column. '- more words'
    and '-- more words' continue after a space. '-xyz' (no space) depends on the line before it:

    * If that line did not fill the item field, the person typed the break, and it sits between
      words ("Butter" + "-salt and pepper" is "Butter salt and pepper").
    * If it filled the field (base_width, the item text on the previous physical line), MealMaster
      cut the text there and lost one character, often in the middle of a word ("chopp" + "-d"),
      so the pieces are joined directly unless the line clearly ended on a whole word.
    """
    cont = cont.strip()
    m = re.match(r"^(-+)(.*)$", cont)
    if not m:
        return f"{base} {cont}".strip()
    dashes, rest = m.groups()
    if len(dashes) == 1 and rest and not rest.startswith(" "):
        last_word = base.rsplit(None, 1)[-1].lower() if base.strip() else ""
        cut_mid_word = (base_width >= ITEM_WIDTH - 1 and base[-1:].isalnum()
                        and last_word not in _WHOLE_WORDS)
        if cut_mid_word or base.endswith("("):
            return base + rest.rstrip()
    rest = rest.strip()
    return f"{base} {rest}" if rest else base


_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_RANGE_ITEM_RE = re.compile(rf"^(?:to|-)\s*({_NUM})\s+(?:([A-Za-z]{{1,2}})\s+)?(\S.*)$", re.IGNORECASE)


def _make_ingredient(qty: str, unit: str, item: str, group: str) -> Ingredient:
    width = len(item)
    item = re.sub(r"\s{2,}", " ", item)
    quantity = parse_quantity(qty)
    raw = "" if quantity is not None or not qty else qty
    canon = canonical_unit(unit, mealmaster=True)
    if canon is None:  # unknown code: keep it visible rather than lose it
        canon = unit
    # "1/2 c  To 1 c Dry sherry": a range. Kept as text ("1/2-1"), which scaling understands.
    m = _RANGE_ITEM_RE.match(item) if quantity is not None else None
    if m:
        upper = parse_quantity(m.group(1))
        second = canonical_unit(m.group(2), mealmaster=True) if m.group(2) else canon
        if upper is not None and upper > quantity and second == canon:
            raw = f"{format_plain(quantity)}-{format_plain(upper)}"
            quantity, item = None, m.group(3)
    ing = Ingredient(item=item, quantity=quantity, unit=canon, group=group, raw_quantity=raw)
    ing._width = width  # length of the last physical line of the item; see _join_continuation
    return ing


def _parse_ingredient_line(line: str, group: str):
    """Fixed-width ingredient line -> list of (side, Ingredient | str), or None.

    side is "L" or "R" for ingredients; "RC" carries continuation text for the previous
    right-hand ingredient.
    """
    split = _split_two_columns(line)
    if split:
        left, right, right_cont = split
        out = []
        lp = _strict_parts(left)
        if lp:
            out.append(_left_entry(lp, group))
        rp = _strict_parts(right)
        if right_cont or (not rp[0] and not rp[1] and rp[2].startswith("-")):
            out.append(("RC", rp[2]))
        else:
            out.append(("R", _make_ingredient(*rp, group)))
        return out
    parts = _strict_parts(line)
    if parts:
        return [_left_entry(parts, group)]
    return None


def _left_entry(parts, group: str):
    qty, unit, item = parts
    if not qty and not unit and item.startswith("-"):
        return ("LC", item)
    return ("L", _make_ingredient(qty, unit, item, group))


def _parse_freeform(line: str, group: str) -> Optional[Ingredient]:
    m = _FREEFORM_RE.match(line)
    if not m:
        return None
    qty_text, token, rest = m.groups()
    quantity = parse_quantity(qty_text)
    if quantity is None:
        return None
    unit = canonical_unit(token, mealmaster=True)
    if unit is not None:
        return Ingredient(item=rest, quantity=quantity, unit=unit, group=group)
    return Ingredient(item=f"{token} {rest}", quantity=quantity, group=group)


def _looks_freeform_with_unit(line: str) -> bool:
    m = _FREEFORM_RE.match(line)
    return bool(m and parse_quantity(m.group(1)) is not None
                and canonical_unit(m.group(2), mealmaster=True))


# ---------------------------------------------------------------- recipe body

def parse_yield(text: str) -> Tuple[Optional[Fraction], str]:
    m = _YIELD_RE.match(text.strip())
    if not m:
        return None, text.strip()
    return parse_quantity(m.group(1)), m.group(2).strip()


_HEADING_RE = re.compile(r"~?-{4,}\s*([^-~\s][^-~]{0,40}?)\s*-\+?-{4,}")
_RULE_RE = re.compile(r"~?[-=_*]{5,}")
_TILDE_DASH_RE = re.compile(r"^~-{1,4}\s*")
_BREAK = "\x00"


def _tidy_rules(line: str) -> List[str]:
    """Split a directions line at rules and dash-framed headings, dropping the dashes.

    "-----", "~--------" and "=====" are rules: they only mark a break. "---For the dish:---"
    is a heading: it becomes a piece of its own. "~--- Combine..." loses its "~---" lead-in.
    Returns the pieces in order; "" marks a paragraph break.
    """
    s = _TILDE_DASH_RE.sub("", line.strip())
    s = _HEADING_RE.sub(lambda m: f"{_BREAK}{m.group(1).strip()}{_BREAK}", s)
    s = _RULE_RE.sub(_BREAK, s)
    return [part.strip() for part in s.split(_BREAK)] if _BREAK in s else [s]


def _unwrap(lines: List[str]) -> str:
    """Join hard-wrapped lines into paragraphs; numbered steps stay on their own line."""
    paragraphs: List[List[str]] = [[]]
    for line in lines:
        pieces = _tidy_rules(line)
        for n, s in enumerate(pieces):
            if not s or n:  # blank line, or the text after a rule: new paragraph
                if paragraphs[-1]:
                    paragraphs.append([])
                if not s:
                    continue
            if n == 0 and _STEP_RE.match(line) and paragraphs[-1]:
                paragraphs.append([])
            paragraphs[-1].append(s)
    return "\n\n".join(" ".join(p) for p in paragraphs if p)


def _next_nonblank(lines: List[str], i: int) -> Optional[str]:
    while i < len(lines):
        if lines[i].strip():
            return lines[i]
        i += 1
    return None


def _parse_block(lines: List[str]) -> Tuple[Optional[Recipe], List[str]]:
    warnings: List[str] = []
    title = ""
    categories: List[str] = []
    yield_text = ""
    i = 0

    # --- header fields (blank lines allowed between them)
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _FIELD_RE.match(line)
        if not m:
            break
        name, value = m.group(1).lower(), m.group(2)
        if name == "title":
            title = value
        elif name == "categories":
            categories = [c.strip() for c in value.split(",") if c.strip()]
        elif name in ("yield", "servings") and not yield_text:
            yield_text = value
            if name == "servings" and value.strip().isdigit():
                yield_text = f"{value.strip()} servings"
        i += 1

    if not title:
        title = "Untitled recipe"
        warnings.append("Recipe without a title; imported as 'Untitled recipe'.")

    # --- ingredients
    ingredients: List[Ingredient] = []
    group = ""
    in_ingredients = True
    contiguous = False  # True right after an ingredient line (no blank in between)
    last_left: Optional[Ingredient] = None
    last_right: Optional[Ingredient] = None
    while i < len(lines) and in_ingredients:
        line = lines[i]
        if not line.strip():
            nxt = _next_nonblank(lines, i + 1)
            if nxt is None:
                i += 1
                break
            if _group_name(nxt) or _parse_ingredient_line(nxt, group) is not None \
                    or _looks_freeform_with_unit(nxt):
                contiguous = False
                i += 1
                continue
            in_ingredients = False
            i += 1
            break
        gname = _group_name(line)
        if gname:
            group = gname
            contiguous = True
            i += 1
            continue
        parsed = _parse_ingredient_line(line, group)
        if parsed is not None:
            for side, value in parsed:
                if side in ("RC", "LC"):
                    target = last_right if side == "RC" else (last_left or (ingredients[-1] if ingredients else None))
                    if target is not None:
                        target.item = _join_continuation(target.item, value, getattr(target, "_width", 0))
                        target._width = len(value.strip())
                    else:
                        target = Ingredient(item=value.lstrip("- ").strip(), group=group)
                        ingredients.append(target)
                        if side == "RC":
                            last_right = target
                        else:
                            last_left = target
                else:
                    if (value.quantity is None and not value.unit and not value.raw_quantity
                            and value.item.startswith("(")):
                        # older exports wrap notes like "(optional)" without a dash
                        target = last_left if side == "L" else last_right
                        if target is not None:
                            target.item += " " + value.item
                            continue
                    ingredients.append(value)
                    if side == "L":
                        last_left = value
                    else:
                        last_right = value
            contiguous = True
            i += 1
            continue
        free = _parse_freeform(line, group)
        if free is not None and line.lstrip()[:1].isdigit():
            ingredients.append(free)
            contiguous = True
            i += 1
            continue
        stripped = line.strip()
        if contiguous and len(stripped) <= 50 and not stripped.endswith("."):
            # e.g. "salt to taste" in a sloppy file: an ingredient with no amount
            ingredients.append(Ingredient(item=stripped, group=group))
            i += 1
            continue
        in_ingredients = False  # first non-ingredient line starts the directions

    directions = _unwrap(lines[i:])
    yq, yu = parse_yield(yield_text) if yield_text else (None, "")

    recipe = Recipe(
        title=title,
        ingredients=ingredients,
        directions=directions,
        categories=categories,
        yield_quantity=yq,
        yield_unit=yu,
        yield_raw=yield_text,
    )
    if not ingredients:
        warnings.append(f"'{title}': no ingredients found.")
    return recipe, warnings


# -------------------------------------------------------------------- export

# Canonical unit -> standard MealMaster code. Units MealMaster has no code for are written as
# part of the item text ("2 cloves garlic"), so nothing is lost and real MealMaster can read it.
_EXPORT_CODES = {
    "tsp": "ts", "Tbsp": "tb", "cup": "c", "pint": "pt", "quart": "qt", "gallon": "ga",
    "fl oz": "fl", "oz": "oz", "lb": "lb", "ml": "ml", "dl": "dl", "l": "l", "mg": "mg",
    "g": "g", "kg": "kg", "can": "cn", "package": "pk", "dash": "ds", "pinch": "pn",
    "slice": "sl", "drop": "dr", "bunch": "bn", "small": "sm", "medium": "md", "large": "lg",
}
_WRAP_WIDTH = ITEM_WIDTH - 3  # wrapped lines stay short, so they are read back as whole words


def _export_amount(q: Fraction) -> str:
    text = format_plain(q)
    if len(text) <= 7 and q.denominator <= 16:
        return text
    text = f"{float(q):.3f}".rstrip("0").rstrip(".")
    return text if len(text) <= 7 else f"{float(q):.7g}"[:7]


def _wrap_words(text: str, width: int) -> List[str]:
    lines: List[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines or [""]


def _export_ingredient(ing: Ingredient) -> List[str]:
    from .units import display_unit, parse_range  # local: keeps the import list at the top short

    qty, code, item = "", "", ing.item
    rng = parse_range(ing.raw_quantity) if ing.quantity is None and ing.raw_quantity else None
    if ing.quantity is not None:
        qty = _export_amount(ing.quantity)
    if ing.unit in _EXPORT_CODES and (ing.quantity is not None or rng):
        code = _EXPORT_CODES[ing.unit]
    elif ing.unit:
        item = f"{display_unit(ing.unit, ing.quantity)} {item}"
    if rng:  # the form MealMaster users write: "1/2 c  To 1 c Dry sherry"
        qty = _export_amount(rng[0])
        item = f"To {_export_amount(rng[1])} {code + ' ' if code else ''}{item}"
    elif ing.quantity is None and ing.raw_quantity:
        item = f"{ing.raw_quantity} {item}"
    first, *rest = _wrap_words(item, _WRAP_WIDTH)
    lines = [f"{qty:>7} {code:<2} {first}".rstrip()]
    lines.extend(f"{'':11}-{more}" for more in rest)
    return lines


def recipe_to_mmf(recipe: Recipe) -> str:
    """One recipe in MealMaster export format (the text parse_text reads back)."""
    from .formatting import credit_line, format_yield

    out = ["MMMMM----- Recipe via Meal-Master (tm) v8.05", " "]
    out.append(f"      Title: {recipe.title}")
    out.append(f" Categories: {', '.join(recipe.categories)}")
    out.append(f"      Yield: {format_yield(recipe) or '1 servings'}")
    out.append(" ")
    group = ""
    for ing in recipe.ingredients:
        if ing.group != group:
            group = ing.group
            if group:
                out.append("MMMMM" + f"{group.upper()}".center(73, "-"))
        out.extend(_export_ingredient(ing))
    out.append(" ")
    paragraphs = [p for p in recipe.directions.split("\n") if p.strip()]
    credit = credit_line(recipe)
    if credit:
        paragraphs.append(credit + ".")
    if recipe.source_url:
        paragraphs.append("Original: " + recipe.source_url)
    for para in paragraphs:
        out.extend("  " + line for line in _wrap_words(para, 75))
        out.append(" ")
    out.append("MMMMM")
    return "\n".join(out) + "\n"


def recipes_to_mmf(recipes) -> str:
    """Several recipes as one MealMaster file."""
    return "\n".join(recipe_to_mmf(r) for r in recipes)
