// Collections: your own named sets of recipes ("Weeknight dinners", "Thanksgiving").
// [{ id, name, ids: [recipe ids] }]. Kept on this device and, signed in, with the account (see app.js).
const KEY = 'sprig.collections';
const listeners = new Set();
export const onChange = (fn) => { listeners.add(fn); };

export function clean(v) {
  const out = [];
  for (const c of Array.isArray(v) ? v : []) {
    const name = typeof c?.name === 'string' ? c.name.trim().slice(0, 60) : '';
    if (!name || typeof c.id !== 'string' || out.some((x) => x.id === c.id)) continue;
    const ids = [...new Set((Array.isArray(c.ids) ? c.ids : []).filter((i) => typeof i === 'string'))].slice(0, 2000);
    out.push({ id: c.id, name, ids });
  }
  return out.slice(0, 100);
}
export function load() {
  try { return clean(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch { return []; }
}
export function replace(list) {
  try { localStorage.setItem(KEY, JSON.stringify(clean(list))); return true; } catch { return false; }
}
export function save(list) {
  const ok = replace(list);
  if (ok) for (const fn of listeners) fn();
  return ok;
}
export const get = (id) => load().find((c) => c.id === id) || null;

/** Make a collection (or return the one that already has this name). Returns its id, or null. */
export function create(name) {
  name = name.trim();
  if (!name) return null;
  const list = load();
  const same = list.find((c) => c.name.toLowerCase() === name.toLowerCase());
  if (same) return same.id;
  const id = `c${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`;
  list.push({ id, name, ids: [] });
  return save(list) ? id : null;
}
export function rename(id, name) {
  const list = load();
  const c = list.find((x) => x.id === id);
  if (!c || !name.trim()) return false;
  c.name = name.trim();
  return save(list);
}
export const remove = (id) => save(load().filter((c) => c.id !== id));

/** Put a recipe in a collection or take it out. */
export function toggle(id, recipeId, on) {
  const list = load();
  const c = list.find((x) => x.id === id);
  if (!c) return false;
  c.ids = c.ids.filter((i) => i !== recipeId);
  if (on) c.ids.push(recipeId);
  return save(list);
}
/** Two sets of collections combined (first sign-in on a device that already has some): same name, one collection. */
export function merge(a, b) {
  const out = clean(a);
  for (const c of clean(b)) {
    const same = out.find((x) => x.name.toLowerCase() === c.name.toLowerCase());
    if (same) same.ids = [...new Set([...same.ids, ...c.ids])];
    else out.push(out.some((x) => x.id === c.id) ? { ...c, id: `${c.id}b` } : c);
  }
  return clean(out);
}
