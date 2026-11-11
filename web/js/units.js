// Quantities, units, scaling, and editor-field handling.
// A line-by-line port of recipelib/units.py, scaling.py, formatting.py and editing.py.
// Pure functions with no DOM access, so they can be tested in Node.
import { ALIASES, CANON, PLURALS } from './unitdata.js';
export { UNIT_CHOICES } from './unitdata.js';

// ---------------------------------------------------------------- fractions

const babs = (a) => (a < 0n ? -a : a);
function gcd(a, b) {
  a = babs(a); b = babs(b);
  while (b) [a, b] = [b, a % b];
  return a || 1n;
}

export class Frac {
  constructor(n, d = 1n) {
    n = BigInt(n); d = BigInt(d);
    if (d === 0n) throw new RangeError('zero denominator');
    if (d < 0n) { n = -n; d = -d; }
    const g = gcd(n, d);
    this.n = n / g;
    this.d = d / g;
  }
  /** "9/4", "3", "0.25" -> Frac (null if not a plain number). */
  static parse(s) {
    s = String(s).trim();
    let m = /^(-?\d+)\/(\d+)$/.exec(s);
    if (m) return +m[2] ? new Frac(BigInt(m[1]), BigInt(m[2])) : null;
    m = /^(-?)(\d*)\.(\d+)$/.exec(s);
    if (m) return new Frac(BigInt(m[1] + (m[2] || '0') + m[3]), 10n ** BigInt(m[3].length));
    m = /^-?\d+$/.exec(s);
    return m ? new Frac(BigInt(s)) : null;
  }
  add(o) { return new Frac(this.n * o.d + o.n * this.d, this.d * o.d); }
  sub(o) { return new Frac(this.n * o.d - o.n * this.d, this.d * o.d); }
  mul(o) { return new Frac(this.n * o.n, this.d * o.d); }
  div(o) { return new Frac(this.n * o.d, this.d * o.n); }
  cmp(o) { const l = this.n * o.d, r = o.n * this.d; return l < r ? -1 : l > r ? 1 : 0; }
  eq(o) { return this.cmp(o) === 0; }
  abs() { return new Frac(babs(this.n), this.d); }
  trunc() { return this.n / this.d; } // BigInt; values here are never negative
  toNumber() { return Number(this.n) / Number(this.d); }
  toString() { return this.d === 1n ? `${this.n}` : `${this.n}/${this.d}`; }
}

const F = (n, d = 1) => new Frac(BigInt(n), BigInt(d));
const ONE = F(1);
const HUNDREDTH = F(1, 100);

/** Round to nearest integer, ties to even (matches Python's round() on a Fraction). */
function roundHalfEven(x) {
  const fl = x.n / x.d;
  const twice = 2n * (x.n % x.d);
  if (twice > x.d) return fl + 1n;
  if (twice < x.d) return fl;
  return fl % 2n === 0n ? fl : fl + 1n;
}

// ---------------------------------------------------------- parse / format

export function parseQuantity(text) {
  const t = String(text).trim();
  if (!t) return null;
  let m = /^(\d+)\s+(\d+)\/(\d+)$/.exec(t);
  if (m) return +m[3] ? F(BigInt(m[1])).add(new Frac(BigInt(m[2]), BigInt(m[3]))) : null;
  m = /^(\d+)\/(\d+)$/.exec(t);
  if (m) return +m[2] ? new Frac(BigInt(m[1]), BigInt(m[2])) : null;
  if (/^(\d*\.\d+|\d+)$/.test(t)) return Frac.parse(t);
  return null;
}

const NUM = String.raw`(?:\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)`;
const RANGE_RE = new RegExp(`^(${NUM})\\s*(?:-|\u2013|to)\\s*(${NUM})$`, 'i');

/** '2-3', '1/2 to 1', '1 1/2-2' -> [low, high] as Fracs; null if not a rising range. */
export function parseRange(text) {
  const m = RANGE_RE.exec(String(text).trim());
  if (!m) return null;
  const low = parseQuantity(m[1]), high = parseQuantity(m[2]);
  if (low == null || high == null || high.cmp(low) <= 0) return null;
  return [low, high];
}

export const formatRange = (low, high) => `${formatQuantity(low)}-${formatQuantity(high)}`;

const trimZeros = (s) => s.replace(/0+$/, '').replace(/\.$/, '');

export function formatQuantity(q) {
  if (q == null) return '';
  if (q.n === 0n) return '0';
  let whole = q.trunc();
  const frac = q.sub(new Frac(whole));
  if (frac.n === 0n) return String(whole);
  for (const denom of [2n, 3n, 4n, 8n]) {
    let nearest = new Frac(roundHalfEven(frac.mul(new Frac(denom))), denom);
    if (frac.sub(nearest).abs().cmp(HUNDREDTH) <= 0 &&
        new Frac(whole).add(nearest).n > 0n) {
      const w = nearest.trunc();
      whole += w;
      nearest = nearest.sub(new Frac(w));
      if (nearest.n === 0n) return String(whole);
      return whole !== 0n ? `${whole} ${nearest}` : String(nearest);
    }
  }
  return trimZeros(q.toNumber().toFixed(2));
}

export function canonicalUnit(text) {
  const t = String(text).trim().replace(/\.$/, '').toLowerCase();
  if (!t) return '';
  if (Object.hasOwn(ALIASES, t)) return ALIASES[t];
  if (CANON.includes(t)) return t;
  return null;
}

export function displayUnit(unit, q) {
  if (q != null && q.cmp(ONE) > 0 && Object.hasOwn(PLURALS, unit)) return PLURALS[unit];
  return unit;
}

export function formatIngredient(ing) {
  const parts = [];
  if (ing.q != null) parts.push(formatQuantity(ing.q));
  else if (ing.raw) parts.push(ing.raw);
  if (ing.unit) {
    let amount = ing.q;
    if (amount == null && ing.raw) {   // "2-3 cups": the top of the range decides
      const rng = parseRange(ing.raw);
      amount = rng ? rng[1] : null;
    }
    parts.push(displayUnit(ing.unit, amount));
  }
  parts.push(ing.item);
  return parts.filter(Boolean).join(' ');
}

export function formatYield(r) {
  if (r.yq != null) return `${formatQuantity(r.yq)} ${r.yu}`.trim();
  return r.yr;
}

/** 'Recipe by Nora Taylor, Nora Cooks' (whichever parts are known), or ''. Same as formatting.credit_line. */
export function creditLine(r) {
  return whoLine('Recipe by', r.src);
}

/** 'Adapted from Nora Taylor, Nora Cooks' for someone's own version of another person's recipe, or ''. */
export function adaptedLine(r) {
  return whoLine('Adapted from', r.adapted);
}

function whoLine(lead, src) {
  let who = [src?.author, src?.name].filter(Boolean);
  if (who.length === 2 && who[0].toLowerCase() === who[1].toLowerCase()) who = who.slice(0, 1);
  return who.length ? `${lead} ${who.join(', ')}` : '';
}

export function recipeToText(r) {
  const lines = [r.title, '='.repeat(r.title.length)];
  const credit = creditLine(r);
  if (credit) lines.push(credit);
  if (r.src?.url) lines.push('Original: ' + r.src.url);
  const adapted = adaptedLine(r);   // phone-only for now (the desktop app has no adapted recipes)
  if (adapted) lines.push(adapted);
  if (r.adapted?.url) lines.push('Original: ' + r.adapted.url);
  if (r.categories.length) lines.push('Categories: ' + r.categories.join(', '));
  const y = formatYield(r);
  if (y) lines.push('Yield: ' + y);
  lines.push('');
  let group = null;
  for (const ing of r.ings) {
    if (ing.group !== group) {
      group = ing.group;
      if (group) lines.push('', `${group}:`);
    }
    lines.push('  ' + formatIngredient(ing));
  }
  if (r.dir) lines.push('', r.dir);
  return lines.join('\n');
}

// ------------------------------------------------------------------ scaling

const VOLUME_TSP = { tsp: F(1), Tbsp: F(3), cup: F(48) };
const WEIGHT_STEPS = [['oz', 'lb', F(16)], ['g', 'kg', F(1000)], ['ml', 'l', F(1000)]];
const NICE_DENOMS = { cup: [2n, 3n, 4n], Tbsp: [2n], tsp: [2n, 4n, 8n] };

function isNice(q, denoms = [2n, 3n, 4n, 8n]) {
  const frac = q.sub(new Frac(q.trunc()));
  if (frac.n === 0n) return true;
  return denoms.some((d) =>
    frac.sub(new Frac(roundHalfEven(frac.mul(new Frac(d))), d)).abs().cmp(HUNDREDTH) <= 0);
}

export function promoteUnit(q, unit) {
  if (Object.hasOwn(VOLUME_TSP, unit)) {
    const tsp = q.mul(VOLUME_TSP[unit]);
    for (const [name, threshold] of [['cup', F(1, 4)], ['Tbsp', F(1)], ['tsp', F(0)]]) {
      const q2 = tsp.div(VOLUME_TSP[name]);
      if (q2.cmp(threshold) >= 0 && isNice(q2, NICE_DENOMS[name])) return [q2, name];
    }
    return [q, unit];
  }
  for (const [small, big, ratio] of WEIGHT_STEPS) {
    if (unit === small && q.cmp(ratio) >= 0 && isNice(q.div(ratio))) return [q.div(ratio), big];
  }
  return [q, unit];
}

export function factorForServings(recipe, target) {
  if (recipe.yq == null || recipe.yq.n <= 0n) {
    throw new Error("This recipe has no numeric yield, so it can't be scaled by servings.");
  }
  if (target.n <= 0n) throw new Error('Target yield must be greater than zero.');
  return target.div(recipe.yq);
}

/** Scaled copy of a recipe. `factor` is a Frac. */
export function scaleRecipe(recipe, factor, smart = true) {
  if (factor.n <= 0n) throw new Error('Scale factor must be greater than zero.');
  const warnings = [];
  const ings = recipe.ings.map((ing) => {
    const copy = { ...ing };
    if (copy.q != null) {
      copy.q = copy.q.mul(factor);
      if (smart && !factor.eq(ONE)) [copy.q, copy.unit] = promoteUnit(copy.q, copy.unit);
    } else if (copy.raw && parseRange(copy.raw)) {
      if (!factor.eq(ONE)) {  // "2-3" doubled is "4-6"; the unit is left alone so both ends share it
        const [low, high] = parseRange(copy.raw);
        copy.raw = formatRange(low.mul(factor), high.mul(factor));
      }
    } else if (copy.raw) {
      warnings.push(`Couldn't scale '${copy.raw} ${copy.item}'; check this one by hand.`);
    }
    return copy;
  });
  let yq = recipe.yq;
  if (yq != null) yq = yq.mul(factor);
  else if (!factor.eq(ONE)) warnings.push('This recipe has no numeric yield, so the yield was left unchanged.');
  return { recipe: { ...recipe, ings, yq, id: null }, factor, warnings };
}

// ------------------------------------------------------- metric / US units
// A line-by-line port of recipelib/convert.py: volume to volume and weight to weight only,
// rounded to amounts you can measure. Ranges and amounts without a number are left alone.

export const SYSTEMS = ['metric', 'us'];
const ML = {
  tsp: F(4929, 1000), Tbsp: F(14787, 1000), 'fl oz': F(29574, 1000), cup: F(236588, 1000),
  pint: F(473176, 1000), quart: F(946353, 1000), gallon: F(3785412, 1000),
};
const GRAMS = { oz: F(283495, 10000), lb: F(4535924, 10000) };
const METRIC_ML = { ml: F(1), dl: F(100), l: F(1000) };
const METRIC_G = { g: F(1), kg: F(1000) };
const THOUSAND = F(1000);

/** Nearest multiple of step, never zero (a tiny amount stays one step). */
function roundTo(value, step) {
  const n = roundHalfEven(value.div(step));
  return new Frac(n || 1n).mul(step);
}

function metric(value, small, big) {
  if (value.cmp(THOUSAND) >= 0) return [roundTo(value.div(THOUSAND), F(1, 20)), big];
  const step = value.cmp(F(10)) < 0 ? F(1, 2) : value.cmp(F(100)) < 0 ? F(5) : F(10);
  const rounded = roundTo(value, step);
  return rounded.cmp(THOUSAND) >= 0 ? [rounded.div(THOUSAND), big] : [rounded, small];
}

function usVolume(ml) {
  if (ml.cmp(ML.Tbsp) < 0) return [roundTo(ml.div(ML.tsp), F(1, 4)), 'tsp'];
  if (ml.cmp(ML.cup.div(F(4))) < 0) return [roundTo(ml.div(ML.Tbsp), F(1, 2)), 'Tbsp'];
  if (ml.cmp(ML.gallon) < 0) return [roundTo(ml.div(ML.cup), F(1, 4)), 'cup'];
  return [roundTo(ml.div(ML.quart), F(1, 4)), 'quart'];
}

function usWeight(grams) {
  if (grams.cmp(GRAMS.lb) < 0) {
    const ounces = grams.div(GRAMS.oz);
    return [roundTo(ounces, ounces.cmp(F(4)) < 0 ? F(1, 4) : F(1, 2)), 'oz'];
  }
  return [roundTo(grams.div(GRAMS.lb), F(1, 4)), 'lb'];
}

/** [quantity, unit] in the given system; unchanged if the unit is not one that converts. */
export function convertAmount(q, unit, system) {
  if (system === 'metric') {
    if (Object.hasOwn(ML, unit)) return metric(q.mul(ML[unit]), 'ml', 'l');
    if (Object.hasOwn(GRAMS, unit)) return metric(q.mul(GRAMS[unit]), 'g', 'kg');
  } else if (system === 'us') {
    if (Object.hasOwn(METRIC_ML, unit)) return usVolume(q.mul(METRIC_ML[unit]));
    if (Object.hasOwn(METRIC_G, unit)) return usWeight(q.mul(METRIC_G[unit]));
  } else {
    throw new Error(`Unknown unit system '${system}'.`);
  }
  return [q, unit];
}

/** A copy of the recipe with its measurable ingredients in the given system. */
export function convertRecipe(recipe, system) {
  if (!SYSTEMS.includes(system)) throw new Error(`Unknown unit system '${system}'.`);
  const ings = recipe.ings.map((ing) => {
    const copy = { ...ing };
    if (copy.q != null && copy.q.n > 0n) [copy.q, copy.unit] = convertAmount(copy.q, copy.unit, system);
    return copy;
  });
  return { ...recipe, ings };
}

// ---------------------------------------------------------- editor helpers

const UNICODE_FRACTIONS = {
  '½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4',
  '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
};

export function normalizeAmount(text) {
  let out = text.trim();
  for (const [ch, plain] of Object.entries(UNICODE_FRACTIONS)) {
    if (out.includes(ch)) out = out.replaceAll(ch, ` ${plain}`);
  }
  return out.split(/\s+/).filter(Boolean).join(' ');
}

export function amountForEditing(ing) {
  const q = ing.q;
  if (q == null) return ing.raw;
  if (q.d === 1n) return String(q.n);
  if (q.d <= 16n) {
    const whole = q.trunc();
    const rem = q.sub(new Frac(whole));
    return whole ? `${whole} ${rem}` : String(rem);
  }
  let d = q.d;
  for (const f of [2n, 5n]) while (d % f === 0n) d /= f;
  if (d === 1n) { // terminating decimal: write it out exactly
    const digits = Math.max(String(q.d).length, 1) + 2;
    return trimZeros(q.toNumber().toFixed(Math.min(digits, 20)));
  }
  return trimZeros(q.toNumber().toFixed(4));
}

/** Build an ingredient from editor cells; null for a completely empty row. */
export function ingredientFromFields(amount, unit, item, group = '') {
  amount = amount.trim(); unit = unit.trim(); item = item.trim(); group = group.trim();
  if (!(amount || unit || item)) return null;
  amount = normalizeAmount(amount);
  const q = parseQuantity(amount);
  const canon = canonicalUnit(unit);
  return { q, raw: q != null ? '' : amount, unit: canon == null ? unit : canon, item, group };
}

export function splitCategories(text) {
  const seen = new Set(), out = [];
  for (let c of text.split(',')) {
    c = c.trim();
    if (c && !seen.has(c.toLowerCase())) { seen.add(c.toLowerCase()); out.push(c); }
  }
  return out;
}

/** "4 servings" -> [Frac(4), "servings"]; text with no leading number -> [null, text]. */
export function parseYield(text) {
  const t = text.trim();
  const m = /^((?:\d+\s+)?\d+\/\d+|\d*\.\d+|\d+)\s*(.*)$/.exec(t);
  if (!m) return [null, t];
  return [parseQuantity(m[1]), m[2].trim()];
}
