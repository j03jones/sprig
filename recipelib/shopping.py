"""Combine the ingredients of several recipes into one shopping list.

The same ingredient from different recipes becomes one line, and amounts that can be added are
added: teaspoons, tablespoons and cups together; ounces and pounds together; grams and
kilograms; millilitres and litres. Amounts in different kinds of unit stay side by side
("2 cups + 1 lb"), and amounts that are not plain numbers ("2-3", "a few") are listed as notes.

web/js/shopping.js is the JavaScript twin; tests/test_shopping.py checks both give the same list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, Iterable, List, Tuple

from .formatting import format_ingredient
from .models import Ingredient, Recipe
from .scaling import _promote_unit, scale_recipe
from .units import display_unit, format_quantity

# unit -> (family, how many of the family's base unit it is)
_FAMILIES: Dict[str, Tuple[str, Fraction]] = {
    "tsp": ("volume", Fraction(1)), "Tbsp": ("volume", Fraction(3)), "fl oz": ("volume", Fraction(6)),
    "cup": ("volume", Fraction(48)), "pint": ("volume", Fraction(96)), "quart": ("volume", Fraction(192)),
    "gallon": ("volume", Fraction(768)),
    "oz": ("weight", Fraction(1)), "lb": ("weight", Fraction(16)),
    "ml": ("metric volume", Fraction(1)), "dl": ("metric volume", Fraction(100)), "l": ("metric volume", Fraction(1000)),
    "g": ("metric weight", Fraction(1)), "kg": ("metric weight", Fraction(1000)),
}
_FAMILY_ORDER = ["", "volume", "weight", "metric volume", "metric weight"]


# Where things are in a shop: aisle -> comma-separated terms (singular, lower case; a term can be
# one word or a phrase). To file an ingredient, the longest term found in its name wins, and
# between terms of the same length the one nearest the end of the name wins, because the last
# word is usually what the thing is ("chicken broth" is a broth, "garlic powder" is a powder).
# tools/gen_unitdata.py copies this table to web/js/aisledata.js so the phone app agrees.
AISLES = [
    ("Produce", "apple, apricot, artichoke, arugula, asparagus, avocado, banana, basil, bean sprout, beet, berry, "
     "blueberry, broccoli, cabbage, cantaloupe, carrot, cauliflower, celery, chard, cherry, chile, chili, chive, "
     "cilantro, cranberry, cucumber, dill, eggplant, endive, fennel, fig, garlic, garlic clove, clove garlic, ginger, "
     "ginger root, grape, grapefruit, green bean, green onion, green pepper, bell pepper, red pepper, "
     "yellow pepper, hot pepper, sweet pepper, chile pepper, chili pepper, jalapeno, kale, kiwi, leek, lemon, "
     "lemon juice, lemon peel, lemon rind, lemon zest, lettuce, lime, lime juice, mango, melon, mint, mushroom, "
     "nectarine, okra, onion, orange, orange peel, orange rind, orange zest, papaya, parsley, parsnip, pea, peach, "
     "pear, pineapple, plum, potato, pumpkin, radish, raspberry, rhubarb, romaine, rosemary, rutabaga, sage, "
     "scallion, shallot, spinach, sprout, squash, strawberry, sweet potato, tangerine, tarragon, thyme, "
     "tomatillo, tomato, turnip, watercress, watermelon, yam, zucchini, herb, salad green"),
    ("Meat & Seafood", "anchovy, bacon, beef, bratwurst, brisket, chicken, chop, chuck, clam, cod, crab, crabmeat, "
     "duck, fillet, filet, fish, flounder, goose, haddock, halibut, ham, hamburger, hot dog, kielbasa, lamb, liver, "
     "lobster, meat, mussel, oyster, pancetta, pepperoni, pork, prawn, prosciutto, rib, roast, salami, salmon, "
     "sausage, scallop, shrimp, sirloin, snapper, sole, steak, tenderloin, trout, tuna, turkey, veal, venison"),
    ("Dairy & Eggs", "butter, buttermilk, cheddar, cheese, cream, cream cheese, creme fraiche, egg, egg white, "
     "egg yolk, feta, half and half, margarine, mascarpone, milk, mozzarella, parmesan, ricotta, sour cream, "
     "whipping cream, whipped cream, yogurt, yoghurt"),
    ("Bakery", "bagel, baguette, bread, bun, crouton, english muffin, pita, roll, tortilla, pie crust, pie shell, "
     "pastry, pizza dough, bread crumb, breadcrumb"),
    ("Baking", "baking powder, baking soda, brown sugar, chocolate, cocoa, coconut, cornmeal, cornstarch, "
     "corn starch, corn syrup, cream of tartar, flour, gelatin, honey, molasses, powdered sugar, shortening, sugar, "
     "syrup, vanilla, extract, yeast, food coloring, marshmallow, graham cracker, evaporated milk, "
     "condensed milk, nut, almond, pecan, walnut, hazelnut, cashew, pistachio, peanut, raisin, date, currant"),
    ("Spices & Seasonings", "allspice, basil leaf, bay leaf, bouillon, caraway, cardamom, cayenne, chili powder, "
     "cinnamon, clove, cumin, curry, dried basil, dried oregano, dried thyme, dried parsley, dried dill, flake, "
     "garlic powder, garlic salt, marjoram, msg, mustard seed, nutmeg, onion powder, onion salt, oregano, paprika, "
     "pepper, peppercorn, poppy seed, powder, saffron, salt, seasoning, sesame seed, spice, turmeric, dry mustard, "
     "red pepper flake, pepper flake, ground ginger, celery seed, celery salt, dill weed, dill seed, fennel seed, coriander, seed"),
    ("Pantry", "barley, bean, broth, stock, bulgur, caper, cereal, chip, couscous, cracker, dressing, jam, jelly, "
     "ketchup, catsup, lentil, macaroni, mayonnaise, mix, mustard, noodle, oat, oatmeal, oil, olive, paste, pasta, "
     "peanut butter, pickle, preserve, quinoa, relish, rice, salsa, sauce, tomato juice, canned tomato, soup, "
     "spaghetti, tahini, tofu, vinegar, coconut milk, split pea, water chestnut, bamboo shoot, pimiento, pimento, "
     "artichoke heart, sauerkraut, applesauce, puree"),
    ("Frozen", "ice cream, sherbet, sorbet, frozen, frozen pea, frozen corn, frozen spinach, frozen broccoli, "
     "frozen strawberry, frozen raspberry, frozen orange juice, frozen vegetable, whipped topping, cool whip, ice"),
    ("Drinks", "ale, beer, bourbon, brandy, champagne, cider, club soda, coffee, cola, cognac, ginger ale, juice, "
     "lemonade, liqueur, rum, sherry, soda, tea, tequila, vermouth, vodka, whiskey, wine, kahlua, amaretto"),
]
OTHER_AISLE = "Other"
AISLE_ORDER = [name for name, _ in AISLES] + [OTHER_AISLE]
# term -> aisle. A term given in two aisles belongs to the later (more specific) one.
AISLE_TERMS: Dict[str, str] = {term.strip(): aisle for aisle, terms in AISLES for term in terms.split(",")}


def aisle_for(item: str) -> str:
    """The aisle an ingredient is found in, from its name ('Onions; chopped' -> 'Produce')."""
    words = item_key(item).split(" ")
    best = None   # (words in the term, position of its last word)
    aisle = OTHER_AISLE
    for size in range(min(3, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            term = " ".join(words[start:start + size])
            if term in AISLE_TERMS and (best is None or (size, start + size) > best):
                best, aisle = (size, start + size), AISLE_TERMS[term]
        if best is not None:
            break
    return aisle


@dataclass
class ShoppingLine:
    key: str                     # stable id for ticking the line off
    name: str                    # "Onion"
    amounts: List[str] = field(default_factory=list)   # ["2 cups", "1 lb"]
    notes: List[str] = field(default_factory=list)     # ["2-3 cloves"], amounts that can't be added
    recipes: List[str] = field(default_factory=list)   # titles that use it
    aisle: str = OTHER_AISLE     # "Produce", "Dairy & Eggs", ...

    @property
    def text(self) -> str:
        parts = self.amounts + self.notes
        return f"{self.name}: {' + '.join(parts)}" if parts else self.name


def item_name(item: str) -> str:
    """'Onions; finely chopped' -> 'Onions' (the part you buy, without the preparation)."""
    item = re.sub(r"^\s*(\([^)]*\)\s*)+", "", item) or item   # "(10 oz) raspberries" -> "raspberries"
    name = re.split(r"[;,(]", item, maxsplit=1)[0]
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return name or re.sub(r"\s+", " ", item).strip()


def item_key(item: str) -> str:
    """Lower-case name with simple plurals folded, so 'Onion' and 'onions' share a line."""
    words = []
    for w in item_name(item).lower().split(" "):
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("oes"):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):   # not asparagus, couscous
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def _display(family: str, total: Fraction) -> Tuple[Fraction, str]:
    """The friendliest unit for a family total (given in the family's base unit)."""
    if family == "volume":
        if total >= 768:                       # a gallon or more: quarts read better than 64 cups
            return total / 192, "quart"
        q, unit = _promote_unit(total, "tsp")
        if unit == "tsp" and total >= 12:      # nothing reads nicely: still say cups, not 50 tsp
            return total / 48, "cup"
        if unit == "tsp" and total >= 3:
            return total / 3, "Tbsp"
        return q, unit
    if family == "weight":
        return (total / 16, "lb") if total >= 16 else (total, "oz")
    if family == "metric volume":
        return (total / 1000, "l") if total >= 1000 else (total, "ml")
    if family == "metric weight":
        return (total / 1000, "kg") if total >= 1000 else (total, "g")
    return total, family[1:]   # "=can" -> "can"; "=" -> no unit


def combine(recipes: Iterable[Recipe]) -> List[ShoppingLine]:
    """One line per ingredient across the given (already scaled) recipes, sorted by name."""
    lines: Dict[str, ShoppingLine] = {}
    totals: Dict[str, Dict[str, Fraction]] = {}
    for recipe in recipes:
        for ing in recipe.ingredients:
            key = item_key(ing.item)
            if not key:
                continue
            line = lines.get(key)
            if line is None:
                line = lines[key] = ShoppingLine(key=key, name=_title(item_name(ing.item)), aisle=aisle_for(ing.item))
                totals[key] = {}
            if recipe.title not in line.recipes:
                line.recipes.append(recipe.title)
            if ing.quantity is not None:
                family, per = _FAMILIES.get(ing.unit, ("=" + ing.unit, Fraction(1)))
                totals[key][family] = totals[key].get(family, Fraction(0)) + ing.quantity * per
            elif ing.raw_quantity:
                note = format_ingredient(Ingredient(item="", unit=ing.unit, raw_quantity=ing.raw_quantity))
                line.notes.append(note)
    for key, line in lines.items():
        def order(family: str):
            return (_FAMILY_ORDER.index(family) if family in _FAMILY_ORDER else len(_FAMILY_ORDER), family)
        for family in sorted(totals[key], key=order):
            q, unit = _display("" if family == "=" else family, totals[key][family])
            line.amounts.append(f"{format_quantity(q)} {display_unit(unit, q)}".strip())
    return sorted(lines.values(), key=lambda l: (l.name.lower(), l.key))


def _title(name: str) -> str:
    return name[:1].upper() + name[1:]


def shopping_list(picks: Iterable[Tuple[Recipe, Fraction]]) -> List[ShoppingLine]:
    """picks: (recipe, scale factor) pairs."""
    return combine(scale_recipe(r, factor=f).recipe if f != 1 else r for r, f in picks)


def to_text(lines: Iterable[ShoppingLine]) -> str:
    return "\n".join(f"[ ] {line.text}" for line in lines)


def by_aisle(lines: Iterable[ShoppingLine]) -> List[Tuple[str, List[ShoppingLine]]]:
    """[(aisle, lines)] in shop order, leaving out aisles with nothing in them."""
    groups: Dict[str, List[ShoppingLine]] = {}
    for line in lines:
        groups.setdefault(line.aisle, []).append(line)
    return [(aisle, groups[aisle]) for aisle in AISLE_ORDER if aisle in groups]


def to_text_by_aisle(lines: Iterable[ShoppingLine]) -> str:
    return "\n\n".join(f"{aisle}\n{to_text(group)}" for aisle, group in by_aisle(lines))
