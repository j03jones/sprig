"""Export the rest of a library as on-demand files for the web app.

    python3 tools/export_more.py --db ~/.local/share/sprig/recipes.db

The web app ships with a built-in set (web/data/recipes.json) that works offline from the first
visit. This writes everything else in the library next to it, in pieces the app fetches only when
needed:

    web/data/more.json                {"v": "<version>", "count": N}       tiny; says which set is current
    web/data/more/<version>/index.json    [id, title, categories, [ingredient names]] for every extra recipe
    web/data/more/<version>/<xx>.json     the full recipes whose id starts with <xx> (256 files)

The app loads the index in the background so search and "What can I make?" cover every recipe, and
fetches one <xx>.json file the first time a recipe in it is opened.

Recipes that are already in the built-in set are left out (exact copies, and near-duplicates the
duplicate finder is sure about). Where the library has a corrected copy of a built-in recipe with
the same title, --refresh-core puts that text into recipes.json under the recipe's existing id, so
stars and edits made on phones stay attached.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recipelib import categories, duplicates  # noqa: E402
from recipelib.db import RecipeDB, content_hash  # noqa: E402
from recipelib.models import Ingredient, Recipe  # noqa: E402
from recipelib.shopping import item_name  # noqa: E402
from recipelib.tidy import tidy_title  # noqa: E402
from tools.export_web import recipe_to_row  # noqa: E402


def recipe_from_row(row) -> Recipe:
    rid, title, cats, yq, yu, yr, ings, directions, *rest = row
    return Recipe(
        title=title, categories=list(cats), directions=directions, tags=list(rest[0]) if rest else [],
        yield_quantity=Fraction(yq) if yq else None, yield_unit=yu, yield_raw=yr,
        ingredients=[Ingredient(item=i[3], quantity=Fraction(i[0]) if i[0] else None, unit=i[2],
                                group=i[4], raw_quantity=i[1]) for i in ings])


def index_row(row) -> list:
    """What search and "What can I make?" need, without amounts or directions."""
    names = []
    for ing in row[6]:
        name = item_name(ing[3])
        if name and name not in names:
            names.append(name)
    return [row[0], row[1], row[2], names]


def split(core_rows, library, progress=print, level=duplicates.HIGH):
    """(core rows, possibly refreshed; extra rows; counts) from the built-in rows and a library."""
    core = [recipe_from_row(r) for r in core_rows]
    core_ids = {r[0] for r in core_rows}
    exact = {content_hash(r)[:10] for r in core}
    for n, r in enumerate(core):
        r.id = -(n + 1)               # negative: a built-in recipe
    for n, r in enumerate(library):
        r.id = n + 1                  # positive: from the library
    dropped, replace = set(), {}
    for r in library:
        if content_hash(r)[:10] in exact or content_hash(r)[:10] in core_ids:
            dropped.add(r.id)
    progress(f"{len(dropped):,} library recipes are exact copies of built-in ones")
    by_id = {r.id: r for r in core + library}
    for g in duplicates.find_duplicate_groups(core + [r for r in library if r.id not in dropped]):
        if duplicates.LEVELS.index(g.level) > duplicates.LEVELS.index(level):
            continue
        built_in = [i for i in g.ids if i < 0]
        mine = [i for i in g.ids if i > 0]
        if not built_in:
            continue
        dropped.update(mine)
        for c in built_in:            # a same-titled copy from the library has the corrected text
            same = [i for i in mine if by_id[i].title.strip().lower() == by_id[c].title.strip().lower()]
            if same and c not in replace:
                replace[c] = same[0]
    extra = [r for r in library if r.id not in dropped]
    return core, extra, dropped, replace, by_id


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True, help="a Sprig library database file")
    ap.add_argument("--data", default=str(root / "web" / "data"), help="the web app's data folder")
    ap.add_argument("--refresh-core", action="store_true",
                    help="also update built-in recipes with the library's corrected text (ids are kept)")
    ap.add_argument("--duplicates", choices=[duplicates.HIGH, duplicates.LIKELY], default=duplicates.HIGH,
                    help="leave out library recipes that match a built-in one with this confidence or better "
                         "(high: same recipe; likely: probably the same). Default: high")
    args = ap.parse_args(argv)

    data_dir = Path(args.data)
    core_path = data_dir / "recipes.json"
    core_doc = json.loads(core_path.read_text(encoding="utf-8"))
    with RecipeDB(args.db) as db:
        library = [db.get_recipe(s.id) for s in db.list_recipes()]
    for r in library:
        if not r.tags:
            categories.apply(r)
    core, extra, dropped, replace, by_id = split(core_doc["recipes"], library, level=args.duplicates)
    print(f"{len(dropped):,} library recipes are already built in; {len(extra):,} extra recipes to export")

    if args.refresh_core:
        rows = []
        for n, row in enumerate(core_doc["recipes"]):
            new = replace.get(-(n + 1))
            if new is not None:
                fresh = recipe_to_row(by_id[new])
                fresh[0] = row[0]                 # keep the id phones already know
                fresh[2] = row[2] or fresh[2]     # and the categories it is filed under
                row = fresh
            row[1] = tidy_title(row[1])          # "PEPPERY RICE" -> "Peppery Rice"
            rows.append(row)
        rows.sort(key=lambda r: r[1].lower())
        core_doc["recipes"] = rows
        core_path.write_text(json.dumps({"v": core_doc.get("v", 1), "recipes": rows}, ensure_ascii=False,
                                        separators=(",", ":")), encoding="utf-8")
        print(f"Refreshed the text of {len(replace):,} built-in recipes ({core_path.stat().st_size / 1e6:.1f} MB)")

    core_ids = {r[0] for r in core_doc["recipes"]}
    rows, seen = [], set(core_ids)
    for r in extra:
        row = recipe_to_row(r)
        full = content_hash(r)
        size = 10
        while full[:size] in seen:        # vanishingly rare: lengthen the id until it is unique
            size += 2
        row[0] = full[:size]
        seen.add(row[0])
        rows.append(row)
    rows.sort(key=lambda row: row[1].lower())

    # the version names the folder, and phones keep a folder's files for good, so it must change
    # whenever anything in them does (a tidied title as much as a new recipe)
    version = hashlib.sha1(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    more_dir = data_dir / "more"
    if more_dir.exists():
        shutil.rmtree(more_dir)
    out = more_dir / version
    out.mkdir(parents=True)
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    (out / "index.json").write_text(dump({"v": version, "recipes": [index_row(r) for r in rows]}), encoding="utf-8")
    shards: dict = {}
    for row in rows:
        shards.setdefault(row[0][:2], []).append(row)
    for prefix, group in shards.items():
        (out / f"{prefix}.json").write_text(dump({"recipes": group}), encoding="utf-8")
    (data_dir / "more.json").write_text(dump({"v": version, "count": len(rows)}), encoding="utf-8")
    total = sum(p.stat().st_size for p in out.iterdir())
    print(f"Wrote {len(rows):,} recipes to {out}: index {(out / 'index.json').stat().st_size / 1e6:.1f} MB, "
          f"{len(shards)} recipe files, {total / 1e6:.1f} MB in all (version {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
