"""Turn a recipe's old free-form category labels into a small set of tidy groups.

The old labels are never thrown away: they are kept on the recipe as `tags` (and stay
searchable). Only `categories` - what you filter by - is replaced by the groups.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence

from . import category_data as data
from .models import Recipe

GROUP_ORDER: List[str] = [g for _, groups in data.SECTIONS for g in groups]
_ORDER_INDEX = {g: i for i, g in enumerate(GROUP_ORDER)}
_TAG_PATTERNS = [(re.compile(p, re.I), g) for p, g in data.TAG_PATTERNS]
_TITLE_RULES = [(re.compile(p, re.I), g) for p, g in data.TITLE_RULES]


def normalize_tag(tag: str) -> str:
    return re.sub(r"\s+", " ", tag.strip().lower())


def in_display_order(names: Iterable[str]) -> List[str]:
    """Sort group names into scheme order; names outside the scheme go last, alphabetically."""
    return sorted(names, key=lambda g: (_ORDER_INDEX.get(g, 999), g.lower()))


def section_of(group: str) -> Optional[str]:
    for section, groups in data.SECTIONS:
        if group in groups:
            return section
    return None


def _groups_for_tag(tag: str) -> List[str]:
    key = normalize_tag(tag)
    if key in data.TAG_MAP:
        return data.TAG_MAP[key]
    for pattern, groups in _TAG_PATTERNS:
        if pattern.search(key):
            return groups
    return []


def _expand(groups: Iterable[str]) -> set:
    out = set(groups)
    for g in list(out):
        out.update(data.IMPLIES.get(g, []))
    return out


def groups_for(tags: Sequence[str], title: str = "") -> List[str]:
    """Groups for a recipe's old labels (title is used only if the labels give nothing)."""
    found: set = set()
    for tag in tags:
        found.update(_groups_for_tag(tag))
    if not found and title:
        for pattern, groups in _TITLE_RULES:  # rules are in priority order; keep at most 3 groups
            if pattern.search(title):
                found.update(groups)
                if len(found) >= 3:
                    break
        if "Vegetarian & Vegan" in found:  # "veggie burgers" are not beef
            found -= {"Meats", "Beef", "Pork", "Poultry", "Seafood"}
    if not found:
        return [data.UNCATEGORIZED]
    return sorted(_expand(found), key=lambda g: _ORDER_INDEX.get(g, 999))


def apply(recipe: Recipe) -> Recipe:
    """Keep the old labels as tags (first time only) and replace categories with groups."""
    if not recipe.tags:
        recipe.tags = list(recipe.categories)
    recipe.categories = groups_for(recipe.tags, recipe.title)
    return recipe


def sectioned(counts: Dict[str, int]):
    """Arrange {group: count} into [(section, [(group, count), ...])] in display order.
    Groups that aren't part of the scheme (ones you typed yourself) go under 'Other'."""
    result = []
    known = set()
    for section, groups in data.SECTIONS:
        rows = [(g, counts[g]) for g in groups if counts.get(g)]
        known.update(groups)
        if rows:
            result.append((section, rows))
    extra = sorted(((g, n) for g, n in counts.items() if g not in known), key=lambda x: x[0].lower())
    if extra:
        for i, (section, rows) in enumerate(result):
            if section == "Other":
                result[i] = (section, rows + extra)
                break
        else:
            result.append(("Other", extra))
    return result


def report(recipes: Iterable[Recipe]) -> str:
    """Plain-text before/after summary, used by the command line and the GUI preview."""
    recipes = list(recipes)
    before, after = Counter(), Counter()
    for r in recipes:
        tags = r.tags or r.categories
        for t in {normalize_tag(t) for t in tags}:
            before[t] += 1
        for g in groups_for(tags, r.title):
            after[g] += 1
    lines = [f"{len(before)} old labels -> {len(after)} groups across {len(recipes):,} recipes", ""]
    for section, rows in sectioned(dict(after)):
        lines.append(section)
        lines.extend(f"  {g:<32}{n:>5}" for g, n in rows)
    return "\n".join(lines)
