"""Save a recipe from a web page into your own library, with credit to its author.

Most recipe websites describe each recipe in a standard machine-readable block (schema.org
"Recipe" JSON-LD). This reads that block for one page the user chose and turns it into a Recipe
with source_author / source_name / source_url filled in. Only the title, ingredients, method and
yield are taken: no photos, stories or notes, which stay on the author's site.

Imported recipes are for the user's own private library. The phone app keeps them out of the
Community list, and the credit line is shown wherever the recipe is.

web/js/webimport.js is the JavaScript twin of recipe_from_schema / parse_ingredient_line;
tests/test_webimport.py checks both give the same result.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import urllib.error
import urllib.request
from typing import Any, List, Optional
from urllib.parse import urlparse

from . import __version__
from . import categories as category_rules
from . import link_data
from .editing import normalize_amount
from .mealmaster import parse_yield
from .models import Ingredient, Recipe
from .units import canonical_unit, parse_quantity

MAX_BYTES = 5 * 1024 * 1024
USER_AGENT = f"Mozilla/5.0 (compatible; Sprig/{__version__}; personal recipe box)"
VEGAN_GROUP = "Vegetarian & Vegan"


class ImportError_(Exception):
    """A friendly message for the person importing."""


# ------------------------------------------------------------------ text helpers

_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: Any) -> str:
    """Plain text: HTML tags removed, entities decoded, whitespace collapsed."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return ""
    text = htmllib.unescape(_TAG_RE.sub(" ", value))
    text = " ".join(text.replace("\u00a0", " ").split())
    return re.sub(r" ([.,;:!?)])", r"\1", text)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _types(node: dict) -> List[str]:
    return [str(t) for t in _as_list(node.get("@type"))]


def _name_of(value: Any) -> str:
    """Author / publisher: a string, an object with a name, or a list of either."""
    names = []
    for v in _as_list(value):
        if isinstance(v, str):
            names.append(clean_text(v))
        elif isinstance(v, dict):
            names.append(clean_text(v.get("name")))
    names = [n for n in names if n]
    return " & ".join(dict.fromkeys(names))


# ------------------------------------------------------------------ finding the recipe

_LD_RE = re.compile(r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
_SITE_RE = re.compile(r"<meta[^>]+property\s*=\s*[\"']og:site_name[\"'][^>]*content\s*=\s*[\"']([^\"']*)[\"']", re.I)


def _walk(node: Any):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk(node[key])


def find_recipe_node(page_html: str) -> Optional[dict]:
    """The first schema.org Recipe object in the page's JSON-LD blocks, or None."""
    for block in _LD_RE.findall(page_html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for node in _walk(data):
            if "Recipe" in _types(node):
                return node
    return None


def site_name_from_html(page_html: str) -> str:
    m = _SITE_RE.search(page_html)
    return clean_text(m.group(1)) if m else ""


# ------------------------------------------------------------------ ingredients

_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_AMOUNT_RE = re.compile(rf"^({_NUM})(?:\s*(?:-|–|to)\s*({_NUM}))?\s*(.*)$")


def parse_ingredient_line(line: str) -> Optional[Ingredient]:
    """'1 1/2 cups flour, sifted' -> 1 1/2 | cup | flour, sifted. Ranges stay as text."""
    text = clean_text(line)
    if not text:
        return None
    text = normalize_amount(text) if re.match(r"^[\d½⅓⅔¼¾⅛⅜⅝⅞]", text) else text
    m = _AMOUNT_RE.match(text)
    quantity, raw, rest = None, "", text
    if m:
        first, second, rest = m.group(1), m.group(2), m.group(3)
        if second:
            raw = f"{first}-{second}"
        else:
            quantity = parse_quantity(first)
            if quantity is None:
                raw = first
    unit = ""
    if m:
        word, _, after = rest.partition(" ")
        canon = canonical_unit(word)
        if canon and after.strip():
            unit, rest = canon, after.strip()
        if rest.lower().startswith("of "):
            rest = rest[3:]
    return Ingredient(item=rest.strip(), quantity=quantity, unit=unit, raw_quantity=raw)


# ------------------------------------------------------------------ method and yield

def _instruction_lines(value: Any) -> List[str]:
    out: List[str] = []
    for v in _as_list(value):
        if isinstance(v, str):
            # one block of text: keep its own line breaks as steps
            for part in re.split(r"\n+|<br\s*/?>|</p>|</li>", v):
                t = clean_text(part)
                if t:
                    out.append(t)
        elif isinstance(v, dict):
            if "HowToSection" in _types(v):
                name = clean_text(v.get("name"))
                if name:
                    out.append(f"{name}:")
                out.extend(_instruction_lines(v.get("itemListElement")))
            else:
                t = clean_text(v.get("text") or v.get("name"))
                if t:
                    out.append(t)
    return out


def _yield_text(value: Any) -> str:
    texts = [clean_text(v) for v in _as_list(value)]
    texts = [t for t in texts if t]
    with_words = [t for t in texts if re.search(r"\d", t) and re.search(r"[A-Za-z]", t)]
    if with_words:
        return with_words[0]
    if texts and re.fullmatch(r"\d+(?:\.\d+)?", texts[0]):
        return f"{texts[0]} servings"
    return texts[0] if texts else ""


# ------------------------------------------------------------------ the whole recipe

def collection_for(url: str) -> Optional[dict]:
    host = urlparse(url).hostname or ""
    host = host[4:] if host.startswith("www.") else host
    for c in link_data.COLLECTIONS:
        home = urlparse(c["home"]).hostname or ""
        if host == (home[4:] if home.startswith("www.") else home):
            return c
    return None


def recipe_from_schema(node: dict, url: str = "", site_name: str = "") -> Recipe:
    """Turn a schema.org Recipe object into a Recipe, with credit filled in."""
    title = clean_text(node.get("name")) or "Untitled recipe"
    ings = [i for i in (parse_ingredient_line(x) for x in _as_list(node.get("recipeIngredient") or node.get("ingredients"))) if i]
    directions = "\n".join(_instruction_lines(node.get("recipeInstructions")))
    yield_text = _yield_text(node.get("recipeYield"))
    yq, yu = parse_yield(yield_text) if yield_text else (None, "")

    labels: List[str] = []
    for key in ("recipeCategory", "recipeCuisine"):
        for v in _as_list(node.get(key)):
            for part in clean_text(v).split(","):
                if part.strip() and part.strip() not in labels:
                    labels.append(part.strip())
    diets = " ".join(str(d) for d in _as_list(node.get("suitableForDiet")))
    known = collection_for(url)
    vegan = "VeganDiet" in diets or "VegetarianDiet" in diets or (known and known.get("group") == VEGAN_GROUP)
    categories = category_rules.groups_for(labels + (["vegan"] if vegan else []), title)
    if vegan and VEGAN_GROUP not in categories:
        categories.append(VEGAN_GROUP)

    author = _name_of(node.get("author"))
    site = (known["site"] if known else "") or _name_of(node.get("publisher")) or site_name
    if not author and known:
        author = known["author"]
    link = url or clean_text(node.get("url") if isinstance(node.get("url"), str) else "")
    return Recipe(
        title=title, ingredients=ings, directions=directions, categories=categories, tags=labels,
        yield_quantity=yq, yield_unit=yu, yield_raw=yield_text,
        source_author=author, source_name=site, source_url=link,
    )


def recipe_from_html(page_html: str, url: str = "") -> Recipe:
    node = find_recipe_node(page_html)
    if node is None:
        raise ImportError_("No recipe was found on that page. It may not be a recipe page, or the site "
                           "doesn't publish its recipes in the standard format. You can still add it by hand "
                           "with the link as the source.")
    return recipe_from_schema(node, url, site_name_from_html(page_html))


def check_url(url: str) -> str:
    url = url.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*:(?!//)", url, re.I) and not re.match(r"^[\w.-]+:\d", url):
        raise ImportError_("Please enter a web address that starts with https://")
    if url and "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ImportError_("Please enter a web address that starts with https://")
    return url


def fetch_recipe(url: str, timeout: float = 20) -> Recipe:
    """Download one recipe page and read its recipe. Raises ImportError_ with a friendly message."""
    url = check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read(MAX_BYTES + 1)
            final_url = res.geturl() or url
            charset = res.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise ImportError_(f"The website answered with an error ({exc.code}). Check the link, or open it in "
                           "your browser to make sure the page loads.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ImportError_(f"Could not reach that website. Check your connection and the link. ({exc})") from exc
    if len(body) > MAX_BYTES:
        raise ImportError_("That page is too large to read.")
    return recipe_from_html(body.decode(charset, errors="replace"), final_url)
