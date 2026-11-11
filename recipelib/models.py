"""Plain data models. No GUI or database code lives here."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional


@dataclass
class Ingredient:
    """One ingredient line.

    quantity is None when the line has no (parseable) amount, e.g. "salt to taste".
    unit is the canonical unit name (see units.py), or "" if none.
    group is the sub-heading the ingredient belongs to (e.g. "Sauce"), or "".
    raw_quantity keeps the original text when quantity could not be parsed.
    """

    item: str
    quantity: Optional[Fraction] = None
    unit: str = ""
    group: str = ""
    raw_quantity: str = ""


@dataclass
class Recipe:
    title: str
    ingredients: List[Ingredient] = field(default_factory=list)
    directions: str = ""
    categories: List[str] = field(default_factory=list)
    yield_quantity: Optional[Fraction] = None
    yield_unit: str = ""  # e.g. "servings", "loaf"
    yield_raw: str = ""  # original yield text
    id: Optional[int] = None
    tags: List[str] = field(default_factory=list)  # original source labels, kept for search
    # Credit for recipes that came from somewhere else (e.g. imported from a web page).
    source_author: str = ""  # e.g. "Nora Taylor"
    source_name: str = ""    # e.g. "Nora Cooks" (website, book, person)
    source_url: str = ""     # link to the original

    @property
    def has_source(self) -> bool:
        return bool(self.source_author or self.source_name or self.source_url)
