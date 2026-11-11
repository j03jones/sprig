"""Command-line front end for the Sprig recipe tooling.

    python -m recipelib import samples/sample.mmf    (files or whole folders)
    python -m recipelib export -o mine.mmf [ids]   (MealMaster file; every recipe if no ids)
    python -m recipelib shopping 3 17 42:2         (one combined list; ID:FACTOR scales a recipe)
    python -m recipelib show 1 --units metric      (or --units us; also works with scale)
    python -m recipelib pantry chicken rice onion  (what can I make with these?)
    python -m recipelib list [search words]
    python -m recipelib show 1
    python -m recipelib scale 1 --servings 12      (or --factor 2)
    python -m recipelib regroup --preview          (show the tidy category groups, change nothing)
    python -m recipelib regroup                    (apply them; backs up the database first)
    python -m recipelib regroup --restore          (put the original categories back)
    python -m recipelib duplicates                 (report near-duplicate groups, change nothing)
    python -m recipelib duplicates --remove high   (merge each 'high' group into its best copy; backs up first)
"""
from __future__ import annotations

import argparse
import sys
from fractions import Fraction
from pathlib import Path

from . import categories, convert, duplicates, shopping
from .db import RecipeDB, default_db_path
from .formatting import credit_line, recipe_to_text
from .mealmaster import parse_file, recipes_to_mmf
from .scaling import scale_recipe


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recipelib")
    ap.add_argument("--db", default=str(default_db_path()), help="database file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="import MealMaster files, or every .mmf/.mm/.txt file in a folder")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("export", help="write recipes to a MealMaster file")
    p.add_argument("ids", nargs="*", type=int, help="recipe ids (default: the whole library)")
    p.add_argument("-o", "--output", required=True, help="file to write")
    p = sub.add_parser("shopping", help="one combined shopping list for several recipes")
    p.add_argument("picks", nargs="+", metavar="ID[:FACTOR]", help="e.g. 12 or 12:2 or 12:1/2")
    p = sub.add_parser("import-url", help="save one recipe from a web page, with credit to its author")
    p.add_argument("url")
    p = sub.add_parser("regroup")
    g2 = p.add_mutually_exclusive_group()
    g2.add_argument("--preview", action="store_true"); g2.add_argument("--restore", action="store_true")
    p = sub.add_parser("duplicates")
    p.add_argument("--limit", type=int, default=40, help="groups to print (default 40)")
    p.add_argument("--remove", choices=list(duplicates.LEVELS),
                   help="merge groups of this confidence or better into their best copy")
    p.add_argument("--yes", action="store_true", help="don't ask before removing")
    p = sub.add_parser("pantry", help="what can I make? recipes from the ingredients you have")
    p.add_argument("have", nargs="+", help='what you have, e.g. chicken rice "soy sauce"')
    p.add_argument("--missing", type=int, default=2, help="allow up to this many missing ingredients (default 2)")
    p.add_argument("--no-basics", action="store_true", help="don't assume water, salt, pepper, sugar, flour, oil, butter")
    p.add_argument("--limit", type=int, default=40)
    p = sub.add_parser("list"); p.add_argument("search", nargs="*")
    p = sub.add_parser("show"); p.add_argument("id", type=int)
    p.add_argument("--units", choices=convert.SYSTEMS, help="show amounts in metric or US units")
    p = sub.add_parser("scale"); p.add_argument("id", type=int)
    p.add_argument("--units", choices=convert.SYSTEMS, help="show amounts in metric or US units")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--factor"); g.add_argument("--servings")
    args = ap.parse_args(argv)

    with RecipeDB(args.db) as db:
        if args.cmd == "import":
            files, problems = _import_targets(args.files)
            for problem in problems:
                print(problem, file=sys.stderr)
            added = skipped = 0
            for path in files:
                try:
                    res = parse_file(path)
                except OSError as e:
                    print(f"{path}: could not be read ({e.strerror or e})", file=sys.stderr)
                    problems.append(str(path))
                    continue
                summary = db.import_recipes(res.recipes, regroup=True)
                added += len(summary.added)
                skipped += len(summary.skipped_duplicates)
                print(f"{path}: {len(summary.added)} added, "
                      f"{len(summary.skipped_duplicates)} duplicates skipped")
                for w in res.warnings:
                    print("  warning:", w)
            if len(files) > 1:
                print(f"Total: {added:,} added, {skipped:,} duplicates skipped from {len(files)} files.")
            if problems:
                return 1
        elif args.cmd == "export":
            ids = args.ids or [s.id for s in db.list_recipes()]
            recipes = [db.get_recipe(i) for i in ids]
            missing = [str(i) for i, r in zip(ids, recipes) if r is None]
            if missing:
                print(f"No recipe with id {', '.join(missing)}", file=sys.stderr)
                return 1
            try:
                Path(args.output).write_text(recipes_to_mmf(recipes), encoding="utf-8")
            except OSError as e:
                print(f"Could not write {args.output} ({e.strerror or e})", file=sys.stderr)
                return 1
            print(f"Wrote {len(recipes):,} recipes to {args.output}")
        elif args.cmd == "shopping":
            picks = []
            for pick in args.picks:
                rid, _, factor = pick.partition(":")
                try:
                    recipe, f = db.get_recipe(int(rid)), Fraction(factor or 1)
                except (ValueError, ZeroDivisionError):
                    print(f"'{pick}' is not ID or ID:FACTOR (for example 12 or 12:2)", file=sys.stderr)
                    return 1
                if recipe is None or f <= 0:
                    print(f"No recipe with id {rid}" if recipe is None else "FACTOR must be greater than zero",
                          file=sys.stderr)
                    return 1
                picks.append((recipe, f))
            print("Shopping list for: " + "; ".join(
                r.title + (f" (x{f})" if f != 1 else "") for r, f in picks))
            print()
            print(shopping.to_text_by_aisle(shopping.shopping_list(picks)))
        elif args.cmd == "import-url":
            from . import webimport
            try:
                recipe = webimport.fetch_recipe(args.url)
            except webimport.ImportError_ as e:
                print(e, file=sys.stderr)
                return 1
            if db.find_duplicate(recipe) is not None:
                print(f"Already in your library: {recipe.title}")
                return 0
            rid = db.add_recipe(recipe)
            print(f"Added {rid}: {recipe.title}  ({credit_line(recipe) or 'no credit found'})")
        elif args.cmd == "regroup":
            if args.preview:
                print(categories.report(db.light_recipes()))
            elif args.restore:
                backup = db.backup()
                print(f"Restored original categories on {db.restore_original_categories():,} recipes."
                      + (f" Backup: {backup}" if backup else ""))
            else:
                backup = db.backup()
                n = db.regroup_all()
                print(f"Filed {n:,} recipes under {len(db.list_categories())} groups."
                      + (f" Backup: {backup}" if backup else ""))
        elif args.cmd == "duplicates":
            groups = duplicates.scan(db)
            if not args.remove:
                print(duplicates.report(groups, db, limit=args.limit))
                return 0
            cutoff = duplicates.LEVELS.index(args.remove)
            chosen = [g for g in groups if duplicates.LEVELS.index(g.level) <= cutoff]
            n = sum(len(g.ids) - 1 for g in chosen)
            print(f"{len(chosen)} groups, {n} recipes would be removed (the first of each group is kept).")
            if not n:
                return 0
            if not args.yes and input("Type 'yes' to continue: ").strip().lower() != "yes":
                print("Cancelled.")
                return 1
            backup = db.backup()
            removed = sum(duplicates.merge_group(db, g.keep_id, g.ids[1:]) for g in chosen)
            print(f"Removed {removed:,} duplicates." + (f" Backup: {backup}" if backup else ""))
        elif args.cmd == "pantry":
            from . import pantry
            recipes = [db.get_recipe(x.id) for x in db.list_recipes()]
            found = pantry.match(recipes, args.have, max_missing=args.missing,
                                 assume_staples=not args.no_basics, limit=args.limit)
            if not found:
                print("No recipes use these. Try naming a few more things you have.")
            for m in found:
                need = f"needs {' and '.join(m.missing)}" if m.missing else "you have everything"
                print(f"{m.recipe.id:>5}  {m.recipe.title}  ({need})")
        elif args.cmd == "list":
            for s in db.list_recipes(search=" ".join(args.search)):
                print(f"{s.id:>5}  {s.title}  [{', '.join(s.categories)}]")
        else:
            recipe = db.get_recipe(args.id)
            if recipe is None:
                print(f"No recipe with id {args.id}", file=sys.stderr)
                return 1
            if args.cmd == "scale":
                try:
                    res = scale_recipe(
                        recipe,
                        factor=Fraction(args.factor) if args.factor else None,
                        target_servings=Fraction(args.servings) if args.servings else None,
                    )
                except ValueError as e:
                    print(e, file=sys.stderr)
                    return 1
                recipe = res.recipe
                for w in res.warnings:
                    print("warning:", w, file=sys.stderr)
            if args.units:
                recipe = convert.convert_recipe(recipe, args.units)
            print(recipe_to_text(recipe))
    return 0


_IMPORT_SUFFIXES = {".mmf", ".mm", ".txt"}


def _import_targets(args):
    """Expand folders into their recipe files. Returns (files, problems)."""
    files, problems = [], []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            found = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in _IMPORT_SUFFIXES)
            if not found:
                problems.append(f"{arg}: no .mmf, .mm or .txt files in this folder")
            files.extend(found)
        elif path.is_file():
            files.append(path)
        else:
            problems.append(f"{arg}: no such file or folder")
    return files, problems


if __name__ == "__main__":
    sys.exit(main())
