"""SQLite-backed recipe library."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from . import categories as category_rules
from .models import Ingredient, Recipe

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS recipes (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    directions   TEXT NOT NULL DEFAULT '',
    yield_qty    TEXT,
    yield_unit   TEXT NOT NULL DEFAULT '',
    yield_raw    TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recipes_title ON recipes(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_recipes_hash ON recipes(content_hash);
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS recipe_categories (
    recipe_id   INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (recipe_id, category_id)
);
CREATE TABLE IF NOT EXISTS recipe_tags (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    tag       TEXT NOT NULL,
    PRIMARY KEY (recipe_id, position)
);
CREATE TABLE IF NOT EXISTS ingredients (
    id        INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    grp       TEXT NOT NULL DEFAULT '',
    qty       TEXT,
    raw_qty   TEXT NOT NULL DEFAULT '',
    unit      TEXT NOT NULL DEFAULT '',
    item      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingredients_recipe ON ingredients(recipe_id, position);
"""


@dataclass
class RecipeSummary:
    id: int
    title: str
    categories: List[str] = field(default_factory=list)


@dataclass
class ImportSummary:
    added: List[int] = field(default_factory=list)
    skipped_duplicates: List[str] = field(default_factory=list)  # titles


def default_db_path() -> Path:
    """Per-user data location on Linux, macOS, and Windows."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "sprig" / "recipes.db"


def content_hash(recipe: Recipe) -> str:
    """Stable fingerprint of a recipe's content, used to spot duplicate imports."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    parts = [norm(recipe.title)]
    for ing in recipe.ingredients:
        q = str(ing.quantity) if ing.quantity is not None else ing.raw_quantity
        parts.append(f"{q}|{norm(ing.unit)}|{norm(ing.item)}")
    parts.append(norm(recipe.directions))
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RecipeDB:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self._has_fts = self._init_fts()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _migrate(self) -> None:
        """Add columns introduced after a library file was first created."""
        have = {r["name"] for r in self.conn.execute("PRAGMA table_info(recipes)")}
        with self.conn:
            for col in ("source_author", "source_name", "source_url"):
                if col not in have:
                    self.conn.execute(f"ALTER TABLE recipes ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")

    # ------------------------------------------------------------- full text

    def _init_fts(self) -> bool:
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts "
                "USING fts5(title, ingredients, directions, categories)"
            )
            return True
        except sqlite3.OperationalError:  # SQLite built without FTS5
            return False

    def _index(self, recipe_id: int, recipe: Recipe) -> None:
        if not self._has_fts:
            return
        self.conn.execute("DELETE FROM recipes_fts WHERE rowid = ?", (recipe_id,))
        self.conn.execute(
            "INSERT INTO recipes_fts(rowid, title, ingredients, directions, categories) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                recipe_id,
                recipe.title,
                " ".join(i.item for i in recipe.ingredients),
                recipe.directions,
                " ".join(list(recipe.categories) + list(recipe.tags)),
            ),
        )

    # ----------------------------------------------------------------- write

    def _write_children(self, recipe_id: int, recipe: Recipe) -> None:
        c = self.conn
        c.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
        c.execute("DELETE FROM recipe_categories WHERE recipe_id = ?", (recipe_id,))
        c.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
        for pos, tag in enumerate(recipe.tags):
            c.execute("INSERT INTO recipe_tags(recipe_id, position, tag) VALUES (?, ?, ?)", (recipe_id, pos, tag))
        for pos, ing in enumerate(recipe.ingredients):
            c.execute(
                "INSERT INTO ingredients(recipe_id, position, grp, qty, raw_qty, unit, item) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    recipe_id, pos, ing.group,
                    str(ing.quantity) if ing.quantity is not None else None,
                    ing.raw_quantity, ing.unit, ing.item,
                ),
            )
        seen = set()
        for name in recipe.categories:
            name = name.strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            c.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (name,))
            cat_id = c.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()["id"]
            c.execute(
                "INSERT INTO recipe_categories(recipe_id, category_id) VALUES (?, ?)",
                (recipe_id, cat_id),
            )

    def add_recipe(self, recipe: Recipe) -> int:
        with self.conn:
            return self._insert(recipe)

    def _insert(self, recipe: Recipe) -> int:
        """Add one recipe inside the caller's transaction."""
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO recipes(title, directions, yield_qty, yield_unit, yield_raw, "
            "content_hash, created_at, updated_at, source_author, source_name, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                recipe.title, recipe.directions,
                str(recipe.yield_quantity) if recipe.yield_quantity is not None else None,
                recipe.yield_unit, recipe.yield_raw, content_hash(recipe), now, now,
                recipe.source_author, recipe.source_name, recipe.source_url,
            ),
        )
        rid = cur.lastrowid
        self._write_children(rid, recipe)
        self._index(rid, recipe)
        recipe.id = rid
        return rid

    def update_recipe(self, recipe: Recipe) -> None:
        if recipe.id is None:
            raise ValueError("Recipe has no id; use add_recipe for new recipes.")
        with self.conn:
            cur = self.conn.execute(
                "UPDATE recipes SET title=?, directions=?, yield_qty=?, yield_unit=?, "
                "yield_raw=?, content_hash=?, updated_at=?, source_author=?, source_name=?, "
                "source_url=? WHERE id=?",
                (
                    recipe.title, recipe.directions,
                    str(recipe.yield_quantity) if recipe.yield_quantity is not None else None,
                    recipe.yield_unit, recipe.yield_raw, content_hash(recipe), _now(),
                    recipe.source_author, recipe.source_name, recipe.source_url, recipe.id,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(f"No recipe with id {recipe.id}")
            self._write_children(recipe.id, recipe)
            self._index(recipe.id, recipe)
            self._prune_categories()

    def delete_recipe(self, recipe_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            if self._has_fts:
                self.conn.execute("DELETE FROM recipes_fts WHERE rowid = ?", (recipe_id,))
            self._prune_categories()

    def _prune_categories(self) -> None:
        self.conn.execute(
            "DELETE FROM categories WHERE id NOT IN (SELECT category_id FROM recipe_categories)"
        )

    # ------------------------------------------------------------------ read

    def get_recipe(self, recipe_id: int) -> Optional[Recipe]:
        row = self.conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if row is None:
            return None
        ings = [
            Ingredient(
                item=r["item"],
                quantity=Fraction(r["qty"]) if r["qty"] is not None else None,
                unit=r["unit"], group=r["grp"], raw_quantity=r["raw_qty"],
            )
            for r in self.conn.execute(
                "SELECT * FROM ingredients WHERE recipe_id = ? ORDER BY position", (recipe_id,)
            )
        ]
        cats = [
            r["name"]
            for r in self.conn.execute(
                "SELECT c.name FROM categories c JOIN recipe_categories rc ON rc.category_id = c.id "
                "WHERE rc.recipe_id = ? ORDER BY c.name COLLATE NOCASE",
                (recipe_id,),
            )
        ]
        return Recipe(
            id=row["id"], title=row["title"], ingredients=ings, directions=row["directions"],
            categories=cats, tags=self._tag_names(recipe_id),
            yield_quantity=Fraction(row["yield_qty"]) if row["yield_qty"] is not None else None,
            yield_unit=row["yield_unit"], yield_raw=row["yield_raw"],
            source_author=row["source_author"], source_name=row["source_name"], source_url=row["source_url"],
        )

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]

    def list_categories(self) -> List[Tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT c.name, COUNT(rc.recipe_id) AS n FROM categories c "
            "JOIN recipe_categories rc ON rc.category_id = c.id "
            "GROUP BY c.id ORDER BY c.name COLLATE NOCASE"
        )
        return [(r["name"], r["n"]) for r in rows]

    def list_recipes(
        self, search: str = "", category: Optional[str] = None, limit: Optional[int] = None
    ) -> List[RecipeSummary]:
        sql = "SELECT r.id, r.title FROM recipes r"
        where, params = [], []
        search = search.strip()
        found: Optional[set] = None
        if search:
            found = set(self._search_ids(search))
            if not found:
                return []
            if len(found) <= 500:   # small result: let SQLite filter (and LIMIT) for us
                where.append(f"r.id IN ({','.join('?' * len(found))})")
                params.extend(sorted(found))
                found = None
            # otherwise filter below: thousands of ids would exceed SQLite's parameter limit
        if category:
            where.append(
                "r.id IN (SELECT rc.recipe_id FROM recipe_categories rc "
                "JOIN categories c ON c.id = rc.category_id WHERE c.name = ?)"
            )
            params.append(category)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.title COLLATE NOCASE"
        if limit and found is None:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()
        if found is not None:
            rows = [row for row in rows if row["id"] in found]
            if limit:
                rows = rows[:int(limit)]
        cats: dict = {}
        if len(rows) > 50:   # one pass over the link table beats a query per recipe
            for r in self.conn.execute(
                "SELECT rc.recipe_id, c.name FROM recipe_categories rc "
                "JOIN categories c ON c.id = rc.category_id ORDER BY c.name COLLATE NOCASE"
            ):
                cats.setdefault(r["recipe_id"], []).append(r["name"])
        else:
            for row in rows:
                cats[row["id"]] = self._category_names(row["id"])
        return [RecipeSummary(id=row["id"], title=row["title"], categories=cats.get(row["id"], []))
                for row in rows]

    def _search_ids(self, text: str) -> List[int]:
        tokens = re.findall(r"\w+", text)
        if not tokens:
            return []
        if self._has_fts:
            query = " ".join(f'"{t}"*' for t in tokens)
            try:
                return [r[0] for r in self.conn.execute(
                    "SELECT rowid FROM recipes_fts WHERE recipes_fts MATCH ?", (query,))]
            except sqlite3.OperationalError:
                pass
        # Fallback: every token must appear in title, directions, ingredients, or categories.
        ids = None
        for t in tokens:
            like = f"%{t}%"
            found = {r[0] for r in self.conn.execute(
                "SELECT id FROM recipes WHERE title LIKE ? OR directions LIKE ? "
                "UNION SELECT recipe_id FROM ingredients WHERE item LIKE ? "
                "UNION SELECT rc.recipe_id FROM recipe_categories rc "
                "JOIN categories c ON c.id = rc.category_id WHERE c.name LIKE ?",
                (like, like, like, like))}
            ids = found if ids is None else ids & found
        return sorted(ids or [])

    # ---------------------------------------------------------------- import

    def find_duplicate(self, recipe: Recipe) -> Optional[int]:
        row = self.conn.execute(
            "SELECT id FROM recipes WHERE content_hash = ?", (content_hash(recipe),)
        ).fetchone()
        return row["id"] if row else None

    def import_recipes(
        self, recipes: Iterable[Recipe], skip_duplicates: bool = True, progress=None,
        regroup: bool = False,
    ) -> ImportSummary:
        """Add recipes, skipping exact duplicates.

        regroup=True keeps each recipe's own labels as tags and files it under the tidy groups
        from category_data.py. progress, if given, is called as progress(done, total) after each
        recipe; returning False from it stops the import early (recipes already added are kept).
        """
        items = list(recipes)
        summary = ImportSummary()
        # One transaction for the whole batch: a commit per recipe made big files take minutes.
        with self.conn:
            for n, r in enumerate(items, 1):
                if skip_duplicates and self.find_duplicate(r) is not None:
                    summary.skipped_duplicates.append(r.title)
                else:
                    if regroup:
                        category_rules.apply(r)
                    summary.added.append(self._insert(r))
                if progress is not None and progress(n, len(items)) is False:
                    break
        return summary

    # ------------------------------------------------------- tidy categories

    def _tag_names(self, recipe_id: int) -> List[str]:
        return [r["tag"] for r in self.conn.execute(
            "SELECT tag FROM recipe_tags WHERE recipe_id = ? ORDER BY position", (recipe_id,))]

    def _category_names(self, recipe_id: int) -> List[str]:
        return [r["name"] for r in self.conn.execute(
            "SELECT c.name FROM categories c JOIN recipe_categories rc ON rc.category_id = c.id "
            "WHERE rc.recipe_id = ? ORDER BY c.name COLLATE NOCASE", (recipe_id,))]

    def _set_categories(self, recipe_id: int, names: List[str]) -> None:
        c = self.conn
        c.execute("DELETE FROM recipe_categories WHERE recipe_id = ?", (recipe_id,))
        for name in names:
            c.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (name,))
            row = c.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
            # names compare case-insensitively; make sure the stored spelling is the one given
            c.execute("UPDATE categories SET name = ? WHERE id = ? AND name COLLATE BINARY <> ?",
                      (name, row["id"], name))
            c.execute("INSERT OR IGNORE INTO recipe_categories(recipe_id, category_id) VALUES (?, ?)",
                      (recipe_id, row["id"]))

    def _reindex(self, recipe_id: int) -> None:
        if not self._has_fts:
            return
        row = self.conn.execute("SELECT title, directions FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        items = " ".join(r["item"] for r in self.conn.execute(
            "SELECT item FROM ingredients WHERE recipe_id = ? ORDER BY position", (recipe_id,)))
        labels = " ".join(self._category_names(recipe_id) + self._tag_names(recipe_id))
        self.conn.execute("DELETE FROM recipes_fts WHERE rowid = ?", (recipe_id,))
        self.conn.execute(
            "INSERT INTO recipes_fts(rowid, title, ingredients, directions, categories) VALUES (?, ?, ?, ?, ?)",
            (recipe_id, row["title"], items, row["directions"], labels))

    def light_recipes(self) -> List[Recipe]:
        """Recipes with only title, categories and tags filled in (cheap; used for reports)."""
        cats: dict = {}
        for r in self.conn.execute(
            "SELECT rc.recipe_id, c.name FROM recipe_categories rc JOIN categories c ON c.id = rc.category_id"
        ):
            cats.setdefault(r["recipe_id"], []).append(r["name"])
        tags: dict = {}
        for r in self.conn.execute("SELECT recipe_id, tag FROM recipe_tags ORDER BY recipe_id, position"):
            tags.setdefault(r["recipe_id"], []).append(r["tag"])
        return [Recipe(id=r["id"], title=r["title"], categories=cats.get(r["id"], []), tags=tags.get(r["id"], []))
                for r in self.conn.execute("SELECT id, title FROM recipes")]

    def is_grouped(self) -> bool:
        """True once the tidy groups have been applied to (at least some of) the library."""
        return self.conn.execute("SELECT 1 FROM recipe_tags LIMIT 1").fetchone() is not None

    def regroup_all(self, progress=None) -> int:
        """File every recipe under the tidy groups. The recipe's current labels are kept as
        tags the first time (so nothing is lost), and later runs re-derive groups from the tags.
        Replaces any categories you assigned by hand. Returns the number of recipes updated."""
        rows = self.conn.execute("SELECT id, title FROM recipes").fetchall()
        with self.conn:
            for n, row in enumerate(rows, 1):
                rid = row["id"]
                tags = self._tag_names(rid)
                if not tags:
                    tags = self._category_names(rid)
                    for pos, tag in enumerate(tags):
                        self.conn.execute("INSERT INTO recipe_tags(recipe_id, position, tag) VALUES (?, ?, ?)",
                                          (rid, pos, tag))
                self._set_categories(rid, category_rules.groups_for(tags, row["title"]))
                self._reindex(rid)
                if progress is not None and progress(n, len(rows)) is False:
                    break
            self._prune_categories()
        return len(rows)

    def restore_original_categories(self) -> int:
        """Undo regroup_all: put each recipe's original labels back as its categories."""
        rows = self.conn.execute("SELECT DISTINCT recipe_id FROM recipe_tags").fetchall()
        with self.conn:
            for row in rows:
                rid = row["recipe_id"]
                self._set_categories(rid, self._tag_names(rid))
                self._reindex(rid)
            self._prune_categories()
        return len(rows)

    def backup(self) -> Optional[str]:
        """Copy the database file next to itself with a timestamp; returns the new path."""
        if self.path == ":memory:":
            return None
        dest = f"{self.path}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        target = sqlite3.connect(dest)
        try:
            self.conn.backup(target)
        finally:
            target.close()
        return dest
