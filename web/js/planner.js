// Meal plan: which recipes are cooked on which day.
// { days: { 'YYYY-MM-DD': [entry, ...] } } where an entry is a recipe { id, f } (f is the scale
// factor as text, e.g. "2") or a note { note: 'Leftovers' }. Kept on this device, and with the
// account when signed in (see app.js). No DOM access here, so it can be tested in Node.
import { Frac } from './units.js';

const KEY = 'sprig.plan';
const KEEP_DAYS = 60;          // older days are dropped when the plan is saved
const MAX_PER_DAY = 12;
const listeners = new Set();
/** Called after every change made on this device (not when a synced copy is put in place). */
export const onChange = (fn) => { listeners.add(fn); };

const pad = (n) => String(n).padStart(2, '0');
/** Local calendar date as 'YYYY-MM-DD'. */
export const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const parseDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };
export function addDays(iso, n) {
  const d = parseDate(iso);
  d.setDate(d.getDate() + n);
  return isoDate(d);
}
/** The Monday on or before the given date. */
export function weekStart(iso) {
  const d = parseDate(iso);
  return addDays(iso, -((d.getDay() + 6) % 7));
}
export const weekDates = (startIso) => Array.from({ length: 7 }, (_, n) => addDays(startIso, n));

const isDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s) && isoDate(parseDate(s)) === s;

function cleanEntry(e) {
  if (e && typeof e.note === 'string' && e.note.trim()) return { note: e.note.trim().slice(0, 80) };
  if (e && typeof e.id === 'string' && e.id) {
    const f = Frac.parse(e.f || '1');
    return { id: e.id, f: f && f.n > 0n ? String(e.f || '1') : '1' };
  }
  return null;
}

/** A well-formed plan from anything (stored text, a synced copy), dropping days older than `today` - 60. */
export function clean(v, today = isoDate(new Date())) {
  const days = {};
  const cutoff = addDays(today, -KEEP_DAYS);
  if (v && typeof v.days === 'object' && v.days) {
    for (const [date, list] of Object.entries(v.days)) {
      if (!isDate(date) || date < cutoff || !Array.isArray(list)) continue;
      const entries = list.map(cleanEntry).filter(Boolean).slice(0, MAX_PER_DAY);
      if (entries.length) days[date] = entries;
    }
  }
  return { days };
}

export function load() {
  try { return clean(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch { return clean(null); }
}

/** Put a whole plan in place (a synced copy); does not count as a change made here. */
export function replace(plan) {
  try { localStorage.setItem(KEY, JSON.stringify(clean(plan))); return true; } catch { return false; }
}

export function save(plan) {
  const ok = replace(plan);
  if (ok) for (const fn of listeners) fn();
  return ok;
}

export function add(date, entry) {
  const plan = load();
  const e = cleanEntry(entry);
  if (!e || !isDate(date)) return false;
  (plan.days[date] ||= []).push(e);
  return save(plan);
}

export function removeAt(date, index) {
  const plan = load();
  if (!plan.days[date]) return false;
  plan.days[date].splice(index, 1);
  return save(plan);
}

export function clearDates(dates) {
  const plan = load();
  for (const d of dates) delete plan.days[d];
  return save(plan);
}

/** The recipes planned on the given dates as [[id, factor Frac], ...], a recipe planned twice added up. */
export function recipesOn(plan, dates) {
  const totals = new Map();
  for (const d of dates) {
    for (const e of plan.days[d] || []) {
      if (!e.id) continue;
      const f = Frac.parse(e.f) || new Frac(1n);
      totals.set(e.id, totals.has(e.id) ? totals.get(e.id).add(f) : f);
    }
  }
  return [...totals.entries()];
}

/** Two plans combined (first sign-in on a device that already has a plan): every entry kept once. */
export function merge(a, b) {
  const out = clean(a);
  for (const [date, list] of Object.entries(clean(b).days)) {
    const have = new Set((out.days[date] || []).map((e) => JSON.stringify(e)));
    for (const e of list) {
      if (!have.has(JSON.stringify(e))) { (out.days[date] ||= []).push(e); have.add(JSON.stringify(e)); }
    }
  }
  return clean(out);
}
