// Turn a schema.org Recipe object (read from one web page the person chose) into a recipe for their
// own private library, with credit to its author. JavaScript twin of recipelib/webimport.py
// (recipe_from_schema / parse_ingredient_line); tests/test_webimport.py checks they agree.
// Only the title, ingredients, method and yield are taken: photos, stories and notes stay on the
// author's site. Pure functions with no DOM access, so they can be tested in Node.
import { normalizeAmount, parseQuantity, canonicalUnit, parseYield } from './units.js';
import { COLLECTIONS } from './linkdata.js';

export const VEGAN_GROUP = 'Vegetarian & Vegan';

const NAMED = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', ndash: '–', mdash: '—', frac12: '½', frac14: '¼', frac34: '¾', deg: '°', rsquo: '’', lsquo: '‘', rdquo: '”', ldquo: '“', hellip: '…', eacute: 'é' };
function unescape(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+\d*);/gi, (m, e) => {
    if (e[0] === '#') {
      const code = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      try { return String.fromCodePoint(code); } catch { return m; }
    }
    return Object.hasOwn(NAMED, e.toLowerCase()) ? NAMED[e.toLowerCase()] : m;
  });
}

/** Plain text: HTML tags removed, entities decoded, whitespace collapsed. */
export function cleanText(value) {
  if (value == null) return '';
  if (typeof value === 'number') return String(value);
  if (typeof value !== 'string') return '';
  return unescape(value.replace(/<[^>]+>/g, ' ')).replace(/ /g, ' ').split(/\s+/).filter(Boolean).join(' ')
    .replace(/ ([.,;:!?)])/g, '$1');
}

const asList = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);
const types = (node) => asList(node && node['@type']).map(String);

function nameOf(value) {
  const names = [];
  for (const v of asList(value)) {
    if (typeof v === 'string') names.push(cleanText(v));
    else if (v && typeof v === 'object') names.push(cleanText(v.name));
  }
  return [...new Set(names.filter(Boolean))].join(' & ');
}

const NUM = String.raw`(?:\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)`;
const AMOUNT_RE = new RegExp(`^(${NUM})(?:\\s*(?:-|–|to)\\s*(${NUM}))?\\s*(.*)$`, 's');

/** '1 1/2 cups flour, sifted' -> 1 1/2 | cup | flour, sifted. Ranges stay as text. */
export function parseIngredientLine(line) {
  let text = cleanText(line);
  if (!text) return null;
  if (/^[\d½⅓⅔¼¾⅛⅜⅝⅞]/.test(text)) text = normalizeAmount(text);
  const m = AMOUNT_RE.exec(text);
  let q = null, raw = '', rest = text, unit = '';
  if (m) {
    const [, first, second] = m;
    rest = m[3];
    if (second) raw = `${first}-${second}`;
    else { q = parseQuantity(first); if (q == null) raw = first; }
    const sp = rest.indexOf(' ');
    const word = sp < 0 ? rest : rest.slice(0, sp);
    const after = sp < 0 ? '' : rest.slice(sp + 1);
    const canon = canonicalUnit(word);
    if (canon && after.trim()) { unit = canon; rest = after.trim(); }
    if (rest.toLowerCase().startsWith('of ')) rest = rest.slice(3);
  }
  return { q, raw, unit, item: rest.trim(), group: '' };
}

function instructionLines(value) {
  const out = [];
  for (const v of asList(value)) {
    if (typeof v === 'string') {
      for (const part of v.split(/\n+|<br\s*\/?>|<\/p>|<\/li>/i)) { const t = cleanText(part); if (t) out.push(t); }
    } else if (v && typeof v === 'object') {
      if (types(v).includes('HowToSection')) {
        const name = cleanText(v.name);
        if (name) out.push(`${name}:`);
        out.push(...instructionLines(v.itemListElement));
      } else {
        const t = cleanText(v.text || v.name);
        if (t) out.push(t);
      }
    }
  }
  return out;
}

function yieldText(value) {
  const texts = asList(value).map(cleanText).filter(Boolean);
  const withWords = texts.filter((t) => /\d/.test(t) && /[A-Za-z]/.test(t));
  if (withWords.length) return withWords[0];
  if (texts.length && /^\d+(?:\.\d+)?$/.test(texts[0])) return `${texts[0]} servings`;
  return texts[0] || '';
}

const bareHost = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
export function collectionFor(url) {
  const host = bareHost(url);
  return host ? COLLECTIONS.find((c) => bareHost(c.home) === host) || null : null;
}

/** The working recipe object the editor expects, with `src` credit filled in. */
export function recipeFromSchema(node, url = '', siteName = '') {
  const title = cleanText(node.name) || 'Untitled recipe';
  const ings = asList(node.recipeIngredient || node.ingredients).map(parseIngredientLine).filter(Boolean);
  const dir = instructionLines(node.recipeInstructions).join('\n');
  const yr = yieldText(node.recipeYield);
  const [yq, yu] = yr ? parseYield(yr) : [null, ''];
  const labels = [];
  for (const key of ['recipeCategory', 'recipeCuisine']) {
    for (const v of asList(node[key])) {
      for (let part of cleanText(v).split(',')) { part = part.trim(); if (part && !labels.includes(part)) labels.push(part); }
    }
  }
  const diets = asList(node.suitableForDiet).map(String).join(' ');
  const known = collectionFor(url);
  const vegan = diets.includes('VeganDiet') || diets.includes('VegetarianDiet') || known?.group === VEGAN_GROUP;
  let author = nameOf(node.author);
  const site = (known && known.site) || nameOf(node.publisher) || siteName;
  if (!author && known) author = known.author;
  const link = url || (typeof node.url === 'string' ? cleanText(node.url) : '');
  return {
    id: null, title, ings, dir, yq, yu, yr, categories: vegan ? [VEGAN_GROUP] : [], tags: labels,
    src: { author, name: site, url: link }, source: 'mine',
  };
}

/**
 * How much of `mine` repeats the wording of `original`: the share of my 4-word runs that also appear in the
 * original (0 to 1). Used to check that an adapted recipe's method is written in the person's own words.
 */
export function wordingOverlap(mine, original) {
  const words = (text) => String(text || '').toLowerCase().replace(/[^a-z0-9½¼¾/\s]+/g, ' ').split(/\s+/).filter(Boolean);
  const runs = (w) => {
    const out = new Set();
    for (let i = 0; i + 4 <= w.length; i++) out.add(w.slice(i, i + 4).join(' '));
    return out;
  };
  const mw = words(mine);
  if (!mw.length) return 0;
  if (mw.length < 4) return ` ${words(original).join(' ')} `.includes(` ${mw.join(' ')} `) ? 1 : 0;   // very short methods
  const a = runs(mw);
  const b = runs(words(original));
  let same = 0;
  for (const x of a) if (b.has(x)) same++;
  return same / a.size;
}

/** Above this share of repeated 4-word runs, an adapted method is too close to the original wording. */
export const MAX_OVERLAP = 0.35;
