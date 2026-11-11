// What can I make? Recipes from the ingredients you have on hand.
// match() is a line-by-line port of recipelib/pantry.py (tested against it); the saved pantry at
// the bottom lives on this device and, signed in, with the account (see app.js).
import { itemKey, itemName } from './shopping.js';

// Things most kitchens have. Matched the same way as your own ingredients.
export const STAPLES = ['water', 'salt', 'pepper', 'sugar', 'flour', 'oil', 'butter', 'ice'];

/** Each thing you have as a list of its words, plurals folded ('Tomatoes' -> ['tomato']). */
export function terms(have) {
  const out = [];
  const seen = new Set();
  for (const h of have) {
    const words = itemKey(h).split(' ').filter(Boolean);
    if (words.length && !seen.has(words.join(' '))) { seen.add(words.join(' ')); out.push(words); }
  }
  return out;
}

const covered = (words, termList) => termList.some((term) => term.every((w) => words.includes(w)));
/** True when a shopping-list line (by its key) is something on the given list of terms. */
export const covers = (key, termList) => covered(key.split(' '), termList);
const cmpText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/** Recipes you can make (or nearly) from `have`, best first: [{ recipe, missing: [names], used }]. */
export function match(recipes, have, { maxMissing = 2, assumeStaples = true, limit = 200 } = {}) {
  const mine = terms(have);
  if (!mine.length) return [];
  const basics = assumeStaples ? terms(STAPLES) : [];
  const found = [];
  for (const r of recipes) {
    const keys = r._keys || (r._keys = r.ings.map((i) => [itemKey(i.item), i.item]));   // worked out once per recipe
    const seen = new Set();
    const missing = [];
    let used = 0, total = 0;
    for (const [key, item] of keys) {
      if (!key || seen.has(key)) continue;
      seen.add(key);
      total++;
      const words = key.split(' ');
      if (covered(words, mine)) used++;
      else if (!covered(words, basics)) {
        missing.push(itemName(item));
        if (missing.length > maxMissing) break;
      }
    }
    if (total >= 2 && used >= 1 && missing.length <= maxMissing) found.push({ recipe: r, missing, used });
  }
  found.sort((a, b) => a.missing.length - b.missing.length || b.used - a.used
    || cmpText(a.recipe.title.toLowerCase(), b.recipe.title.toLowerCase()));
  return found.slice(0, limit);
}

// ------------------------------------------------------------ the saved pantry
// { have: ['chicken', 'rice', ...], staples: true }

const KEY = 'sprig.pantry';
const listeners = new Set();
export const onChange = (fn) => { listeners.add(fn); };

export function clean(v) {
  const have = [];
  for (const x of Array.isArray(v?.have) ? v.have : []) {
    const t = typeof x === 'string' ? x.trim().slice(0, 60) : '';
    if (t && !have.some((y) => y.toLowerCase() === t.toLowerCase())) have.push(t);
  }
  return { have: have.slice(0, 200), staples: v?.staples !== false };
}
export function load() {
  try { return clean(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch { return clean(null); }
}
export function replace(p) {
  try { localStorage.setItem(KEY, JSON.stringify(clean(p))); return true; } catch { return false; }
}
export function save(p) {
  const ok = replace(p);
  if (ok) for (const fn of listeners) fn();
  return ok;
}
/** Add one thing or several separated by commas. */
export function add(text) {
  const p = load();
  p.have.push(...text.split(/[,\n]/));
  return save(p);
}
export function remove(name) {
  const p = load();
  p.have = p.have.filter((x) => x !== name);
  return save(p);
}
export function setStaples(on) {
  const p = load();
  p.staples = !!on;
  return save(p);
}
export const merge = (a, b) => clean({ have: [...clean(a).have, ...clean(b).have], staples: clean(a).staples });
