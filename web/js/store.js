// The user's own changes (new recipes, edits to built-in ones, deletions) live in IndexedDB.
// The built-in library is read-only data/recipes.json; the two are merged in app.js.
// Record shapes: a full recipe record (see model.js toRecord), or {id, deleted: true}.
const DB_NAME = 'sprig-user';
const STORE = 'recipes';

let dbPromise = null;
const memory = new Map(); // fallback when IndexedDB is unavailable (e.g. some private modes)
export let persistent = true;

function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      if (!('indexedDB' in globalThis)) return reject(new Error('no indexedDB'));
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id' });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error('blocked'));
    }).catch((err) => { persistent = false; console.warn('IndexedDB unavailable:', err); return null; });
  }
  return dbPromise;
}

async function tx(mode, fn) {
  const db = await open();
  if (!db) return fn(null);
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    let result;
    Promise.resolve(fn(t.objectStore(STORE))).then((r) => { result = r; });
    t.oncomplete = () => resolve(result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

const wrap = (req) => new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); });

export async function all() {
  return tx('readonly', (s) => (s ? wrap(s.getAll()) : [...memory.values()]));
}
export async function put(rec) {
  return tx('readwrite', (s) => { if (s) s.put(rec); else memory.set(rec.id, rec); });
}
export async function putMany(recs) {
  return tx('readwrite', (s) => { for (const r of recs) { if (s) s.put(r); else memory.set(r.id, r); } });
}
export async function remove(id) {
  return tx('readwrite', (s) => { if (s) s.delete(id); else memory.delete(id); });
}
export async function removeMany(ids) {
  return tx('readwrite', (s) => { for (const id of ids) { if (s) s.delete(id); else memory.delete(id); } });
}
