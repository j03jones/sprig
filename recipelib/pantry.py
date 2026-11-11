"""What can I make? Find recipes from the ingredients you have on hand.

An ingredient counts as "on hand" when every word of something you listed appears in its name
("chicken" covers "Chicken breasts; boned"; "soy sauce" covers "Dark soy sauce" but not "Soy milk").
Kitchen basics (water, salt, pepper, ...) can be assumed. Recipes are ranked by how little is
missing, then by how many of your ingredients they use.

web/js/pantry.js is the JavaScript twin; tests/test_js_twins.py checks both give the same answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from .models import Recipe
from .shopping import item_key, item_name

# Things most kitchens have. Matched the same way as your own ingredients.
STAPLES = ["water", "salt", "pepper", "sugar", "flour", "oil", "butter", "ice"]


@dataclass
class PantryMatch:
    recipe: Recipe
    missing: List[str] = field(default_factory=list)   # names of what you would still need
    used: int = 0                                      # how many of the recipe's ingredients you have


def terms(have: Iterable[str]) -> List[List[str]]:
    """Each thing you have as a list of its words, plurals folded ('Tomatoes' -> ['tomato'])."""
    out = []
    for h in have:
        words = [w for w in item_key(h).split(" ") if w]
        if words and words not in out:
            out.append(words)
    return out


def _covered(words: Sequence[str], term_list: Sequence[Sequence[str]]) -> bool:
    return any(all(w in words for w in term) for term in term_list)


def match(recipes: Iterable[Recipe], have: Iterable[str], max_missing: int = 2,
          assume_staples: bool = True, limit: int = 200) -> List[PantryMatch]:
    """Recipes you can make (or nearly) from `have`, best first.

    A recipe is listed when it uses at least one thing you named, has at least two ingredients,
    and is missing no more than max_missing.
    """
    mine = terms(have)
    if not mine:
        return []
    basics = terms(STAPLES) if assume_staples else []
    found: List[PantryMatch] = []
    for r in recipes:
        seen, missing, used, total = set(), [], 0, 0
        for ing in r.ingredients:
            key = item_key(ing.item)
            if not key or key in seen:
                continue
            seen.add(key)
            total += 1
            words = key.split(" ")
            if _covered(words, mine):
                used += 1
            elif not _covered(words, basics):
                missing.append(item_name(ing.item))
                if len(missing) > max_missing:
                    break
        if total >= 2 and used >= 1 and len(missing) <= max_missing:
            found.append(PantryMatch(recipe=r, missing=missing, used=used))
    found.sort(key=lambda m: (len(m.missing), -m.used, m.recipe.title.lower()))
    return found[:limit]
