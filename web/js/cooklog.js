// Cook log: what you have made, how you rated it, and your own private notes.
// { [recipeId]: { made: ['YYYY-MM-DD', ...], rating: 0-5, note: '' } }
// Kept on this device and, signed in, with the account (see app.js). Nobody else sees it.
const KEY = 'sprig.cooklog';
const MAX_MADE = 60;        // dates kept per recipe (the count shown is of these)
const listeners = new Set();
export const onChange = (fn) => { listeners.add(fn); };

const isDate = (s) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s);

function cleanEntry(e) {
  const made = [...new Set((Array.isArray(e?.made) ? e.made : []).filter(isDate))].sort().slice(-MAX_MADE);
  const rating = Number.isInteger(e?.rating) && e.rating >= 1 && e.rating <= 5 ? e.rating : 0;
  const note = typeof e?.note === 'string' ? e.note.trim().slice(0, 2000) : '';
  return made.length || rating || note ? { made, rating, note } : null;
}

export function clean(v) {
  const out = {};
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    for (const [id, e] of Object.entries(v).slice(0, 5000)) {
      const entry = cleanEntry(e);
      if (entry) out[id] = entry;
    }
  }
  return out;
}
export function load() {
  try { return clean(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch { return {}; }
}
export function replace(log) {
  try { localStorage.setItem(KEY, JSON.stringify(clean(log))); return true; } catch { return false; }
}
export function save(log) {
  const ok = replace(log);
  if (ok) for (const fn of listeners) fn();
  return ok;
}
export const get = (id) => load()[id] || { made: [], rating: 0, note: '' };

function change(id, fn) {
  const log = load();
  const entry = log[id] || { made: [], rating: 0, note: '' };
  fn(entry);
  log[id] = entry;
  return save(log);
}
/** Record that the recipe was made on a day ('YYYY-MM-DD'); once per day. */
export const markMade = (id, date) => change(id, (e) => { if (!e.made.includes(date)) e.made.push(date); });
/** Take back the most recent "made" (a slip of the thumb). */
export const unmarkLast = (id) => change(id, (e) => { e.made.sort(); e.made.pop(); });
/** 1 to 5 stars; the same rating again clears it. */
export const setRating = (id, rating) => change(id, (e) => { e.rating = e.rating === rating ? 0 : rating; });
export const setNote = (id, note) => change(id, (e) => { e.note = note; });

/** 'Made 3 times, last on 2026-11-09' pieces for display: { times, last } (last is '' if never). */
export function summary(entry) {
  const made = [...(entry?.made || [])].sort();
  return { times: made.length, last: made.length ? made[made.length - 1] : '' };
}

/** Recipe ids you have made, most recent first: [[id, entry], ...]. */
export function recent(log) {
  return Object.entries(log).filter(([, e]) => e.made.length)
    .sort((a, b) => (summary(b[1]).last < summary(a[1]).last ? -1 : summary(b[1]).last > summary(a[1]).last ? 1 : 0));
}

/** Two logs combined (first sign-in on a device that already has one): every day counted once,
 *  the first log's rating kept unless it has none, and both notes kept if they differ. */
export function merge(a, b) {
  const out = clean(a);
  for (const [id, e] of Object.entries(clean(b))) {
    const mine = out[id];
    if (!mine) { out[id] = e; continue; }
    out[id] = {
      made: [...mine.made, ...e.made],
      rating: mine.rating || e.rating,
      note: !e.note || e.note === mine.note ? mine.note : mine.note ? `${mine.note}\n${e.note}` : e.note,
    };
  }
  return clean(out);
}
