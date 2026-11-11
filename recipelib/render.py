"""HTML rendering of a recipe for display (kept free of any GUI imports)."""
from __future__ import annotations

from html import escape

from .formatting import credit_line, format_ingredient, format_yield
from .models import Recipe


def recipe_to_html(recipe: Recipe) -> str:
    parts = [f"<h1>{escape(recipe.title)}</h1>"]
    meta = []
    if recipe.categories:
        meta.append("<b>Categories:</b> " + escape(", ".join(recipe.categories)))
    y = format_yield(recipe)
    if y:
        meta.append("<b>Yield:</b> " + escape(y))
    if recipe.tags:
        meta.append('<span style="color:#777"><b>Original labels:</b> ' + escape(", ".join(recipe.tags)) + "</span>")
    if meta:
        parts.append("<p>" + "<br>".join(meta) + "</p>")
    credit = credit_line(recipe)
    if credit or recipe.source_url:
        line = escape(credit) if credit else "Source"
        if recipe.source_url:
            line += f' &middot; <a href="{escape(recipe.source_url, quote=True)}">View the original recipe</a>'
        parts.append(f'<p style="background:#eef6ef;padding:6px">{line}</p>')

    if recipe.ingredients:
        parts.append("<h2>Ingredients</h2>")
        open_list = False
        group = None
        for ing in recipe.ingredients:
            if ing.group != group:
                if open_list:
                    parts.append("</ul>")
                    open_list = False
                group = ing.group
                if group:
                    parts.append(f"<h3>{escape(group)}</h3>")
            if not open_list:
                parts.append("<ul>")
                open_list = True
            parts.append(f"<li>{escape(format_ingredient(ing))}</li>")
        if open_list:
            parts.append("</ul>")

    if recipe.directions:
        parts.append("<h2>Directions</h2>")
        for para in recipe.directions.split("\n\n"):
            for line in para.split("\n"):
                parts.append(f"<p>{escape(line)}</p>")
    return "\n".join(parts)
