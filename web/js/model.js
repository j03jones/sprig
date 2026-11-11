// Conversions between the three shapes a recipe takes:
//   row     compact array in data/recipes.json (the built-in library)
//   recipe  working object used by the UI
//   record  JSON-safe object stored in IndexedDB / backup files (the user's own changes)
import { Frac } from './units.js';

const q = (s) => (s === '' || s == null ? null : Frac.parse(s));

export function fromRow(row) {
  const [id, title, categories, yq, yu, yr, ings, dir, tags] = row;
  return {
    id, title, categories, tags: tags || [], yq: q(yq), yu, yr, dir, source: 'base',
    ings: ings.map(([iq, raw, unit, item, group]) => ({ q: q(iq), raw, unit, item, group })),
  };
}

/** A recipe from the on-demand index: enough to list, search and match by ingredient. The amounts,
 *  directions and yield arrive later (see app.js ensureFull), so `stub` is true until then. */
export function fromIndexRow([id, title, categories, names]) {
  return {
    id, title, categories: categories || [], tags: [], yq: null, yu: '', yr: '', dir: '', source: 'base', stub: true,
    ings: (names || []).map((item) => ({ q: null, raw: '', unit: '', item, group: '' })),
  };
}

export function toRecord(r) {
  return {
    id: r.id, title: r.title, categories: r.categories, tags: r.tags || [],
    yq: r.yq == null ? '' : String(r.yq), yu: r.yu, yr: r.yr, dir: r.dir,
    ings: r.ings.map((i) => [i.q == null ? '' : String(i.q), i.raw, i.unit, i.item, i.group]),
    ...(hasSource(r) ? { src: { author: r.src.author || '', name: r.src.name || '', url: r.src.url || '' } } : {}),
    ...(isAdapted(r) ? { adapted: { author: r.adapted.author || '', name: r.adapted.name || '', url: r.adapted.url || '' } } : {}),
    ...(r.kind === 'link' ? { kind: 'link' } : {}),
    updated: Date.now(),
  };
}

/** True when the recipe came from somewhere else and carries a credit (author, site or link). */
export const hasSource = (r) => !!(r && r.src && (r.src.author || r.src.name || r.src.url));

/** True for the person's own version of someone else's recipe ("Adapted from …"). */
export const isAdapted = (r) => !!(r && r.adapted && (r.adapted.author || r.adapted.name || r.adapted.url));

export function fromRecord(rec, source) {
  const r = fromRow([rec.id, rec.title, rec.categories, rec.yq, rec.yu, rec.yr, rec.ings, rec.dir, rec.tags]);
  r.source = source;
  if (rec.src) r.src = { author: rec.src.author || '', name: rec.src.name || '', url: rec.src.url || '' };
  if (rec.adapted) r.adapted = { author: rec.adapted.author || '', name: rec.adapted.name || '', url: rec.adapted.url || '' };
  if (rec.kind === 'link') r.kind = 'link';
  return r;
}
