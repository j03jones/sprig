// Nutrition and food cost for a recipe. Pure functions, no DOM (tested in Node).
//
// Each ingredient line is recognised against the table in nutridata.js, turned into grams (from its
// weight, its volume with the food's weight per cup, or a count of pieces), then
//   nutrition = grams x the food's values per 100 g
//   cost      = amount x the price you entered, in whatever unit you buy it by
// Anything that cannot be worked out (no amount, an unknown food, "1 can") is listed as not counted
// instead of being guessed, and the totals say how much of the recipe they cover.
import { FOODS, FREE } from './nutridata.js';
import { itemKey, itemName } from './shopping.js';
import { parseRange } from './units.js';

const ML = { tsp: 4.929, Tbsp: 14.787, 'fl oz': 29.574, cup: 236.588, pint: 473.176, quart: 946.353, gallon: 3785.41, ml: 1, dl: 100, l: 1000 };
const GRAMS = { oz: 28.3495, lb: 453.592, g: 1, kg: 1000 };
const CUP_ML = 236.588;
const SIZES = { small: 0.75, medium: 1, large: 1.25 };
const TINY = { pinch: 0.4, dash: 0.6, drop: 0.05 };          // grams: they barely count, but they are not "unknown"
const PIECES = new Set(['', 'piece', 'head', 'small', 'medium', 'large']);

// ---- recognising the food in an ingredient line
const table = new Map();                                      // folded name -> entry
for (const [name, kcal, protein, carbs, fat, sodium, cup, each, units] of FOODS) {
  table.set(itemKey(name), { term: itemKey(name), name, kcal, protein, carbs, fat, sodium, cup, each, units });
}
const FREE_KEYS = new Set(FREE.map(itemKey));

/** { key, entry } for an ingredient name. `key` is what prices are saved under: the food's name when it
 *  is recognised ("Onions; chopped" and "chopped onion" are both "onion"), else the line's own name. */
export function identify(item) {
  const words = itemKey(item).split(' ').filter(Boolean);
  let best = null;                                            // [size, end position, entry]
  for (let size = Math.min(3, words.length); size > 0; size--) {
    for (let start = 0; start + size <= words.length; start++) {
      const e = table.get(words.slice(start, start + size).join(' '));
      if (e && (!best || size > best[0] || (size === best[0] && start + size > best[1]))) best = [size, start + size, e];
    }
    if (best) break;                                          // a longer name beats any shorter one
  }
  if (best) return { key: best[2].term, entry: best[2] };
  return { key: words.join(' '), entry: null };
}

/** The amount of an ingredient as a number (the middle of a range like "2-3"), or null ("to taste"). */
export function amountOf(ing) {
  if (ing.q != null) return ing.q.toNumber();
  if (ing.raw) {
    const r = parseRange(ing.raw);
    if (r) return (r[0].toNumber() + r[1].toNumber()) / 2;
  }
  return null;
}

/** What one ingredient line weighs or measures: { g, ml, n } with whatever can be worked out (else null). */
export function measure(ing, entry) {
  const q = amountOf(ing);
  if (q == null || !(q > 0)) return null;
  const unit = ing.unit || '';
  let g = null, ml = null, n = null;
  if (Object.hasOwn(GRAMS, unit)) g = q * GRAMS[unit];
  else if (Object.hasOwn(ML, unit)) ml = q * ML[unit];
  else if (entry && Object.hasOwn(entry.units, unit)) g = q * entry.units[unit];
  else if (Object.hasOwn(TINY, unit)) g = q * TINY[unit];
  else if (PIECES.has(unit)) {
    n = q * (Object.hasOwn(SIZES, unit) ? SIZES[unit] : 1);
    if (entry && entry.each) g = n * entry.each;
  } else return null;
  if (g == null && ml != null && entry && entry.cup) g = (ml / CUP_ML) * entry.cup;
  if (ml == null && g != null && entry && entry.cup) ml = (g / entry.cup) * CUP_ML;
  if (n == null && g != null && entry && entry.each) n = g / entry.each;
  return { g, ml, n };
}

// ---- nutrition
export const NUTRIENTS = [['kcal', 'Calories', ''], ['fat', 'Fat', 'g'], ['carbs', 'Carbs', 'g'], ['protein', 'Protein', 'g'], ['sodium', 'Sodium', 'mg']];

/** Totals for the whole recipe as written (scale the recipe first to get a scaled total), and per serving. */
export function nutrition(recipe) {
  const total = { kcal: 0, fat: 0, carbs: 0, protein: 0, sodium: 0 };
  const counted = [];
  const skipped = [];
  for (const ing of recipe.ings) {
    const { key, entry } = identify(ing.item);
    if (FREE_KEYS.has(key) && !(entry && entry.kcal)) continue;     // water, ice: nothing to count
    const m = amountOf(ing) == null ? null : measure(ing, entry);
    if (!entry || !m || m.g == null) { skipped.push({ ing, why: !entry ? 'unknown food' : amountOf(ing) == null ? 'no amount' : 'cannot be weighed' }); continue; }
    const k = m.g / 100;
    for (const f of Object.keys(total)) total[f] += k * entry[f];
    counted.push(ing);
  }
  const yq = recipe.yq ? recipe.yq.toNumber() : 0;
  const servings = yq > 0 ? yq : 0;
  const per = servings ? Object.fromEntries(Object.entries(total).map(([f, v]) => [f, v / servings])) : null;
  const lines = counted.length + skipped.length;
  return { total, per, servings, counted: counted.length, skipped, lines, coverage: lines ? counted.length / lines : 0 };
}

// ---- cost
/** The ways a price can be given: what a price per X is measured in. */
export const PRICE_UNITS = {
  lb: { label: 'lb', kind: 'g', size: 453.592 }, oz: { label: 'oz', kind: 'g', size: 28.3495 },
  kg: { label: 'kg', kind: 'g', size: 1000 }, g: { label: 'g', kind: 'g', size: 1 },
  gallon: { label: 'gallon', kind: 'ml', size: 3785.41 }, quart: { label: 'quart', kind: 'ml', size: 946.353 },
  l: { label: 'liter', kind: 'ml', size: 1000 }, cup: { label: 'cup', kind: 'ml', size: CUP_ML },
  each: { label: 'each', kind: 'n', size: 1 }, dozen: { label: 'dozen', kind: 'n', size: 12 },
};

const LIQUID = /\b(oil|milk|cream|broth|stock|juice|wine|vinegar|sauce|syrup|water|beer|honey|molasses)\b/;
/** The sensible price unit to start with for an ingredient line. */
export function defaultPriceUnit(ing, entry) {
  const u = ing.unit || '';
  if (Object.hasOwn(GRAMS, u)) return u === 'g' || u === 'kg' ? 'kg' : 'lb';
  if (Object.hasOwn(ML, u)) return !entry || LIQUID.test(entry.term) ? 'quart' : 'lb';
  return !entry || entry.each ? 'each' : 'lb';
}

/** What one ingredient line costs at a saved price { p, per }; null if the amounts cannot be matched. */
export function lineCost(ing, entry, price) {
  if (!price || !(price.p >= 0) || !Object.hasOwn(PRICE_UNITS, price.per)) return null;
  const m = measure(ing, entry);
  if (!m) return null;
  const pu = PRICE_UNITS[price.per];
  const amount = m[pu.kind];
  return amount == null ? null : (amount / pu.size) * price.p;
}

/**
 * Cost of a recipe: `prices` is { [key]: { p, per } }. Returns each line's cost (or why not), the total of
 * what could be costed, and which lines still need a price.
 */
export function costing(recipe, prices) {
  const lines = [];
  let total = 0;
  let missing = 0;
  for (const ing of recipe.ings) {
    const { key, entry } = identify(ing.item);
    const free = FREE_KEYS.has(key);
    const price = prices && Object.hasOwn(prices, key) ? prices[key] : null;
    const hasAmount = amountOf(ing) != null;
    let cost = null;
    let state;
    if (free) state = 'free';
    else if (!hasAmount) state = 'noamount';
    else if (!price) { state = 'noprice'; missing++; }
    else {
      cost = lineCost(ing, entry, price);
      if (cost == null) { state = 'noconvert'; missing++; } else { state = 'ok'; total += cost; }
    }
    lines.push({ ing, key, entry, price, cost, state });
  }
  const yq = recipe.yq ? recipe.yq.toNumber() : 0;
  const servings = yq > 0 ? yq : 0;
  return { lines, total, servings, perServing: servings ? total / servings : null, missing, complete: missing === 0 };
}

/** Menu price that gives a target food cost % ("30" = cost is 30% of the price). */
export const suggestedPrice = (costPerServing, targetPct) => (targetPct > 0 ? costPerServing / (targetPct / 100) : null);
/** Food cost % at a menu price. */
export const foodCostPct = (costPerServing, price) => (price > 0 ? (costPerServing / price) * 100 : null);

export { itemName };
