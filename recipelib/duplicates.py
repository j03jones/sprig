"""Find near-duplicate recipes (same dish, small differences) and merge them safely.

Exact copies are already skipped on import (see db.content_hash). This module finds the
rest: retitled copies, "&" vs "and", translated titles, small ingredient tweaks, and the
same ingredients with rewritten directions. Nothing here deletes anything by itself;
``merge_group`` is only called after the user has reviewed a group.

Pure Python, no dependencies. ~5,500 recipes are compared in about a second.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Recipe

STOP = set("a an and the of or with in on for to from at by as is it its into over per".split())
DESC = set(
    "chopped minced sliced diced grated shredded fresh frozen canned dried ground large small medium "
    "lean boneless skinless softened melted cooked uncooked finely coarsely thinly optional opt divided "
    "drained peeled cut crushed packed beaten whole fat low plain unsalted salted extra".split())
UNITS = set(
    "tsp tbsp cup cups pint quart gallon oz lb g kg ml l can package clove slice pinch dash bunch "
    "stick small medium large each count".split())
TITLE_NOISE = {"recipe", "recipes", "style"}

# Confidence levels, best first.
HIGH, LIKELY, POSSIBLE = "high", "likely", "possible"
LEVELS = (HIGH, LIKELY, POSSIBLE)
LEVEL_LABEL = {
    HIGH: "Same recipe",
    LIKELY: "Probably the same recipe",
    POSSIBLE: "Possibly the same recipe",
}


def _words(s: str) -> List[str]:
    return re.findall(r"[a-z]+", s.lower())


def _title_tokens(title: str) -> frozenset:
    title = re.sub(r"\([^)]*\)|\[[^\]]*\]|<[^>]*>", " ", title)
    return frozenset(w for w in _words(title) if w not in STOP and w not in TITLE_NOISE)


def _ingredient_words(r: Recipe) -> frozenset:
    out = set()
    for ing in r.ingredients:
        for w in _words(ing.item):
            if w in STOP or w in DESC or w in UNITS or len(w) < 3:
                continue
            if w.endswith("s") and len(w) > 4:
                w = w[:-1]
            out.add(w)
    return frozenset(out)


def _shingles(text: str, k: int = 3) -> frozenset:
    w = [x for x in _words(text) if x not in STOP]
    return frozenset(hash(tuple(w[i:i + k])) for i in range(max(0, len(w) - k + 1)))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def classify(ing: float, title: float, directions: float) -> Optional[str]:
    """Map the three similarity scores (0..1) to a confidence level, or None for 'different'."""
    if ing >= 0.85 and directions >= 0.8:
        return HIGH
    if ing >= 0.9 and (title >= 0.6 or directions >= 0.5):
        return LIKELY
    if (ing >= 0.6 and title >= 0.7) or (ing >= 0.8 and directions >= 0.5):
        return POSSIBLE
    return None


@dataclass
class Pair:
    a: int
    b: int
    ingredients: float
    title: float
    directions: float
    level: str


@dataclass
class DuplicateGroup:
    ids: List[int]                       # best copy first
    level: str                           # weakest link inside the group
    pairs: List[Pair] = field(default_factory=list)

    @property
    def keep_id(self) -> int:
        return self.ids[0]

    @property
    def label(self) -> str:
        return LEVEL_LABEL[self.level]


def _keep_score(r: Recipe) -> Tuple:
    """Higher = nicer copy to keep: fuller directions and ingredients, has a yield, more labels."""
    return (len(r.directions.strip()), len(r.ingredients), 1 if (r.yield_quantity or r.yield_raw) else 0,
            len(r.categories) + len(r.tags))


def find_duplicate_groups(recipes: Sequence[Recipe], ignored: Iterable[Tuple[int, int]] = ()) -> List[DuplicateGroup]:
    """Cluster near-duplicate recipes. ``recipes`` need ids, titles, ingredients and directions.
    ``ignored`` holds (id, id) pairs the user has said are NOT duplicates."""
    ignore = {tuple(sorted(p)) for p in ignored}
    prep = []
    for r in recipes:
        prep.append((_title_tokens(r.title), _ingredient_words(r), _shingles(r.directions)))

    df = collections.Counter(w for _, iw, _ in prep for w in iw)
    common = {w for w, n in df.items() if n > max(0.04 * len(prep), 25)}
    post: Dict[str, List[int]] = collections.defaultdict(list)
    rare_sets = []
    for i, (_, iw, _) in enumerate(prep):
        rare = iw - common
        rare_sets.append(rare)
        for w in rare:
            post[w].append(i)

    pairs: List[Pair] = []
    for i, rare in enumerate(rare_sets):
        if len(prep[i][1]) < 3:
            continue
        cnt: collections.Counter = collections.Counter()
        for w in rare:
            for j in post[w]:
                if j > i:
                    cnt[j] += 1
        for j, c in cnt.items():
            if c < 3 or c < 0.5 * min(len(rare), len(rare_sets[j])):
                continue
            ia, ib = recipes[i].id, recipes[j].id
            if ia is not None and ib is not None and tuple(sorted((ia, ib))) in ignore:
                continue
            ing = _jaccard(prep[i][1], prep[j][1])
            tit = _jaccard(prep[i][0], prep[j][0])
            dire = _jaccard(prep[i][2], prep[j][2])
            level = classify(ing, tit, dire)
            if level:
                pairs.append(Pair(i, j, ing, tit, dire, level))

    # union-find over the flagged pairs
    parent = list(range(len(recipes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        parent[find(p.a)] = find(p.b)
    members: Dict[int, List[int]] = collections.defaultdict(list)
    for i in {x for p in pairs for x in (p.a, p.b)}:
        members[find(i)].append(i)
    by_root: Dict[int, List[Pair]] = collections.defaultdict(list)
    for p in pairs:
        by_root[find(p.a)].append(p)

    groups = []
    rank = {lv: n for n, lv in enumerate(LEVELS)}
    for root, idx in members.items():
        idx.sort(key=lambda i: _keep_score(recipes[i]), reverse=True)
        ps = by_root[root]
        level = max((p.level for p in ps), key=lambda lv: rank[lv])   # weakest link
        groups.append(DuplicateGroup(
            ids=[recipes[i].id for i in idx], level=level,
            pairs=[Pair(recipes[p.a].id, recipes[p.b].id, p.ingredients, p.title, p.directions, p.level)
                   for p in ps]))
    groups.sort(key=lambda g: (rank[g.level], recipes_title(recipes, g.ids[0]).lower()))
    return groups


def recipes_title(recipes: Sequence[Recipe], rid: int) -> str:
    for r in recipes:
        if r.id == rid:
            return r.title
    return ""


# ---------------------------------------------------------------- database helpers

def _ensure_ignore_table(db) -> None:
    db.conn.execute("CREATE TABLE IF NOT EXISTS duplicate_ignores("
                    "a INTEGER NOT NULL, b INTEGER NOT NULL, PRIMARY KEY(a, b))")


def ignored_pairs(db) -> List[Tuple[int, int]]:
    _ensure_ignore_table(db)
    return [(r[0], r[1]) for r in db.conn.execute("SELECT a, b FROM duplicate_ignores")]


def ignore_group(db, ids: Sequence[int]) -> None:
    """Remember that these recipes are different dishes so they are not flagged again."""
    _ensure_ignore_table(db)
    with db.conn:
        for n, a in enumerate(ids):
            for b in ids[n + 1:]:
                lo, hi = sorted((a, b))
                db.conn.execute("INSERT OR IGNORE INTO duplicate_ignores(a, b) VALUES (?, ?)", (lo, hi))


def scan(db, progress=None) -> List[DuplicateGroup]:
    """Load every recipe from the database and find the duplicate groups."""
    ids = [r[0] for r in db.conn.execute("SELECT id FROM recipes ORDER BY id")]
    recipes = []
    for n, rid in enumerate(ids, 1):
        recipes.append(db.get_recipe(rid))
        if progress is not None and progress(n, len(ids)) is False:
            return []
    return find_duplicate_groups(recipes, ignored_pairs(db))


def merge_group(db, keep_id: int, remove_ids: Sequence[int]) -> int:
    """Keep one recipe, fold the others' categories and tags into it, delete the rest.
    The caller should take ``db.backup()`` first. Returns the number of recipes removed."""
    keep = db.get_recipe(keep_id)
    if keep is None:
        raise ValueError(f"No recipe with id {keep_id}")
    removed = 0
    for rid in remove_ids:
        if rid == keep_id:
            continue
        other = db.get_recipe(rid)
        if other is None:
            continue
        for c in other.categories:
            if c.lower() not in {x.lower() for x in keep.categories}:
                keep.categories.append(c)
        for t in other.tags:
            if t.lower() not in {x.lower() for x in keep.tags}:
                keep.tags.append(t)
        removed += 1
    db.update_recipe(keep)
    for rid in remove_ids:
        if rid != keep_id:
            db.delete_recipe(rid)
    return removed


def report(groups: Sequence[DuplicateGroup], db, limit: Optional[int] = None) -> str:
    counts = collections.Counter(g.level for g in groups)
    extra = sum(len(g.ids) - 1 for g in groups)
    lines = [f"{len(groups)} duplicate groups ({extra} recipes could be removed): "
             + ", ".join(f"{counts[lv]} {lv}" for lv in LEVELS)]
    titles = {rid: t for rid, t in db.conn.execute("SELECT id, title FROM recipes")}
    for g in (groups if limit is None else groups[:limit]):
        lines.append(f"\n[{g.level}] {g.label}")
        for n, rid in enumerate(g.ids):
            lines.append(f"  {'keep  ' if n == 0 else 'remove'} {rid:>5}  {titles.get(rid, '?')}")
        best = max(g.pairs, key=lambda p: p.ingredients + p.directions)
        lines.append(f"         ingredients {best.ingredients:.0%}, title {best.title:.0%}, directions {best.directions:.0%}")
    return "\n".join(lines)
