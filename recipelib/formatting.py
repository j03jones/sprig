"""Human-readable text for ingredients, yields, and whole recipes."""
from __future__ import annotations

from .models import Ingredient, Recipe
from .units import display_unit, format_quantity, parse_range


def format_ingredient(ing: Ingredient) -> str:
    parts = []
    if ing.quantity is not None:
        parts.append(format_quantity(ing.quantity))
    elif ing.raw_quantity:
        parts.append(ing.raw_quantity)
    if ing.unit:
        amount = ing.quantity
        if amount is None and ing.raw_quantity:   # "2-3 cups": the top of the range decides
            rng = parse_range(ing.raw_quantity)
            amount = rng[1] if rng else None
        parts.append(display_unit(ing.unit, amount))
    parts.append(ing.item)
    return " ".join(p for p in parts if p)


def format_yield(recipe: Recipe) -> str:
    if recipe.yield_quantity is not None:
        return f"{format_quantity(recipe.yield_quantity)} {recipe.yield_unit}".strip()
    return recipe.yield_raw


def credit_line(recipe: Recipe) -> str:
    """'Recipe by Nora Taylor, Nora Cooks' (whichever parts are known), or ''."""
    who = [p for p in (recipe.source_author, recipe.source_name) if p]
    if len(who) == 2 and who[0].lower() == who[1].lower():
        who = who[:1]
    return ("Recipe by " + ", ".join(who)) if who else ""


def recipe_to_text(recipe: Recipe) -> str:
    lines = [recipe.title, "=" * len(recipe.title)]
    credit = credit_line(recipe)
    if credit:
        lines.append(credit)
    if recipe.source_url:
        lines.append("Original: " + recipe.source_url)
    if recipe.categories:
        lines.append("Categories: " + ", ".join(recipe.categories))
    y = format_yield(recipe)
    if y:
        lines.append("Yield: " + y)
    lines.append("")
    group = None
    for ing in recipe.ingredients:
        if ing.group != group:
            group = ing.group
            if group:
                lines.extend(["", f"{group}:"])
        lines.append("  " + format_ingredient(ing))
    if recipe.directions:
        lines.extend(["", recipe.directions])
    return "\n".join(lines)
