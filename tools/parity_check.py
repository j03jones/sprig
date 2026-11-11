"""Check that the web app's JavaScript scaling/formatting gives byte-identical output to the
Python library for every recipe in web/data/recipes.json.

    python3 tools/parity_check.py
"""
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from recipelib.formatting import format_ingredient, format_yield, recipe_to_text  # noqa: E402
from recipelib.models import Ingredient, Recipe  # noqa: E402
from recipelib.scaling import scale_recipe  # noqa: E402

FACTORS = ["1/2", "2", "3/2", "3", "1/3", "4", "5/4", "7/3"]


def load():
    data = json.loads((root / "web" / "data" / "recipes.json").read_text(encoding="utf-8"))
    out = []
    for rid, title, cats, yq, yu, yr, ings, dirs, *_tags in data["recipes"]:
        out.append((rid, Recipe(
            title=title, categories=cats, directions=dirs,
            yield_quantity=Fraction(yq) if yq else None, yield_unit=yu, yield_raw=yr,
            ingredients=[Ingredient(item=i[3], quantity=Fraction(i[0]) if i[0] else None,
                                    unit=i[2], group=i[4], raw_quantity=i[1]) for i in ings])))
    return out


def render(r, factor, smart):
    if factor is None:
        res = r
        warn = []
    else:
        s = scale_recipe(r, factor=factor, smart_units=smart)
        res, warn = s.recipe, s.warnings
    return "\n".join([format_yield(res)] + [format_ingredient(i) for i in res.ingredients] + warn)


def main():
    recipes = load()
    expected = {}
    for rid, r in recipes:
        expected[f"{rid}|text"] = recipe_to_text(r)
        for f in FACTORS:
            for smart in (True, False):
                expected[f"{rid}|{f}|{int(smart)}"] = render(r, Fraction(f), smart)
    proc = subprocess.run(["node", str(root / "tools" / "parity.mjs")], capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr)
        return 1
    got = json.loads(proc.stdout)
    bad = [k for k in expected if got.get(k) != expected[k]]
    print(f"{len(expected):,} comparisons, {len(bad)} mismatches")
    for k in bad[:5]:
        print("--", k, "\nPY:", repr(expected[k][:300]), "\nJS:", repr(got.get(k, "<missing>")[:300]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
