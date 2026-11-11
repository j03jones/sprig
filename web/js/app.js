import {
  Frac, UNIT_CHOICES, adaptedLine, amountForEditing, convertRecipe, creditLine, factorForServings, formatIngredient, formatYield,
  ingredientFromFields, parseYield, recipeToText, scaleRecipe, splitCategories,
} from './units.js';
import * as shop from './shopping.js';
import * as planner from './planner.js';
import * as pantry from './pantry.js';
import * as collections from './collections.js';
import * as cooklog from './cooklog.js';
import * as prices from './prices.js';
import { priceBook, recipeCosting } from './costui.js';
import { transferPage } from './transferui.js';
import { fromIndexRow, fromRecord, fromRow, hasSource, isAdapted, toRecord } from './model.js';
import { COLLECTIONS } from './linkdata.js';
import { MAX_OVERLAP, VEGAN_GROUP, recipeFromSchema, wordingOverlap } from './webimport.js';
import * as store from './store.js';
import { SECTIONS } from './groups.js';
import { addStars, buzz, confetti, copyText, emojiFor, greeting, icon, isStarred, onStarsChange, replaceStars, sprigArt, starIds, tile, toggleStar } from './ui.js';
import { restoreTimers, timerChips } from './timers.js';
import * as cloud from './cloud.js';
import { accountCard, viewAdmin, viewJoin } from './account.js';
import * as photos from './photos.js';
import { linkFor, packRecipe, unpackRecipe } from './sharelink.js';
import { qrSvg } from './qr.js';

const $app = document.getElementById('app');
const $toast = document.getElementById('toast');
const PAGE = 60;
const collator = new Intl.Collator(undefined, { sensitivity: 'base' });   // much faster than localeCompare over 28,000 titles
const UNITS_KEY = 'sprig.units';

// ------------------------------------------------------------------- helpers

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  const props = {};
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (['value', 'checked', 'disabled', 'selected'].includes(k)) props[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  Object.assign(el, props); // after children, so <select> values stick
  return el;
}

// Like el.replaceChildren(), but skips null/false/'' and flattens arrays (the DOM method would
// turn those into the text "null" or "false").
function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false && k !== ''));
}

let toastTimer;
function toast(msg, ms = 2600) {
  $toast.textContent = msg;
  $toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $toast.classList.remove('show'), ms);
}

/** A message with one OK button (sign-in / sign-up confirmations and the like). */
function infoDialog(title, message, okLabel = 'OK') {
  return new Promise((resolve) => {
    const dlg = h('dialog', { class: 'infodialog', 'aria-labelledby': 'dlg-title' },
      h('h2', { id: 'dlg-title' }, title),
      message && h('p', null, message),
      h('div', { class: 'row' }, h('button', { class: 'primary', onclick: () => dlg.close() }, okLabel)));
    dlg.addEventListener('close', () => { resolve(); dlg.remove(); });
    document.body.append(dlg);
    dlg.showModal();
  });
}

function confirmDialog(message, okLabel = 'OK', danger = false) {
  return new Promise((resolve) => {
    const dlg = h('dialog', null,
      h('p', null, message),
      h('div', { class: 'row' },
        h('button', { onclick: () => dlg.close('no') }, 'Cancel'),
        h('button', { class: danger ? 'primary danger' : 'primary', onclick: () => dlg.close('yes') }, okLabel)));
    dlg.addEventListener('close', () => { resolve(dlg.returnValue === 'yes'); dlg.remove(); });
    document.body.append(dlg);
    dlg.showModal();
  });
}

/** A page header: a soft leaf-green wash with the sprig in its corner ('hero' is the taller home-page one). */
function band(kind, ...kids) {
  return h('header', { class: `band ${kind}` }, kids, sprigArt());
}
const pageHead = (title, sub) => band('page', h('h1', null, title), sub && h('p', { class: 'sub' }, sub));

function celebrate(from) {
  confetti(from);
  buzz([30, 40, 30]);
  toast('Plated! Nice cooking 🍽️', 3200);
}

const trim0 = (s) => (s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s);
const num = (f, places) => trim0(f.toNumber().toFixed(places));

// ------------------------------------------------------------------- library

const lib = { more: [], moreState: 'idle', base: [], mine: new Map(), all: [], byId: new Map(), cats: [], cloud: [], me: null, restaurants: [], syncError: '', planSyncError: '', libPhotos: {}, avatars: {} };

// ---- the rest of the library: on-demand files next to the built-in recipes (tools/export_more.py).
// data/more.json names the current set; its index gives every extra recipe's title, categories and
// ingredient names (so search and "What can I make?" cover them); the full recipes are in 256
// files fetched one at a time, the first time a recipe in them is needed. The service worker keeps
// whatever has been fetched, so it works offline afterwards.
const more = { v: null, files: new Map(), failed: new Set() };
/** Fetch a library file and keep a copy for offline use. The service worker does the same, but on a
 *  first visit it is not in charge yet when these files are fetched, so the page saves them itself. */
async function fetchKept(url, init) {
  let cache = null;
  try { cache = await caches.open('sprig-more'); } catch { /* no cache storage (some private modes) */ }
  try {
    const res = await fetch(url, init);
    if (res.ok && cache) cache.put(url, res.clone()).catch(() => {});
    return res;
  } catch (err) {
    const saved = cache && await cache.match(url);
    if (saved) return saved;
    throw err;
  }
}
async function loadMore() {
  if (navigator.connection?.saveData) return;            // the person asked their browser to save data
  lib.moreState = 'loading';
  try {
    const info = await (await fetchKept('data/more.json', { cache: 'no-cache' })).json();
    if (!info?.v) throw new Error('no extra recipes published');
    const res = await fetchKept(`data/more/${info.v}/index.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const index = await res.json();
    more.v = info.v;
    lib.more = index.recipes.map(fromIndexRow);
    lib.moreState = 'ready';
    tidyMoreCache(info.v);
  } catch (err) {
    lib.moreState = 'unavailable';                       // offline before the first full load: built-in recipes only
    console.info('The full library is not available right now:', err.message || err);
  }
  rebuild();
  // show the bigger library where it matters, without disturbing someone who is typing or reading
  const view = document.body.dataset.view;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '') && document.activeElement.value;
  if (!document.querySelector('dialog[open]') && !typing && ['list', 'loading', 'shop', 'plan', 'collection', 'pantry'].includes(view)) route();
}
/** Forget files from an earlier export of the library. */
async function tidyMoreCache(v) {
  try {
    const cache = await caches.open('sprig-more');
    for (const req of await cache.keys()) {
      if (req.url.includes('/data/more/') && !req.url.includes(`/data/more/${v}/`)) cache.delete(req);
    }
  } catch { /* no cache storage */ }
}
/** Make sure these recipes have their amounts and directions. Resolves to the ids that could not be fetched. */
async function ensureFull(ids) {
  const stubs = ids.map((id) => lib.byId.get(id)).filter((r) => r?.stub);
  const prefixes = [...new Set(stubs.map((r) => r.id.slice(0, 2)))];
  await Promise.all(prefixes.map((prefix) => {
    if (!more.files.has(prefix)) {
      more.files.set(prefix, (async () => {
        const res = await fetchKept(`data/more/${more.v}/${prefix}.json`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        for (const row of (await res.json()).recipes) {
          const r = lib.more.find((x) => x.id === row[0]);
          if (!r || !r.stub) continue;
          Object.assign(r, fromRow(row), { stub: false });
          delete r._keys;
          r._hay = [r.title, r.categories.join(' '), (r.tags || []).join(' '), r.ings.map((i) => i.item).join(' '), r.dir].join('\n').toLowerCase();
        }
      })().catch((err) => { more.files.delete(prefix); throw err; }));   // a failed fetch can be tried again later
    }
    return more.files.get(prefix).catch(() => {});
  }));
  return stubs.filter((r) => r.stub).map((r) => r.id);
}
/** Placeholder while a recipe's file is on its way (or could not be fetched). */
function viewFetching(id, again) {
  setView('loading', 'list');
  fill($app, pageHead(lib.byId.get(id)?.title || 'One moment'), h('div', { class: 'sk' }), h('div', { class: 'sk' }), h('div', { class: 'sk' }));
  ensureFull([id]).then((missing) => {
    if (location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent).includes(id) === false) return;   // moved on
    if (!missing.length) return again();
    fill($app, pageHead(lib.byId.get(id)?.title || 'Recipe'),
      h('p', null, 'This recipe has not been opened on this device before, so it needs a connection the first time. Connect and try again; after that it works offline.'),
      h('div', { class: 'row' }, h('button', { class: 'primary', type: 'button', onclick: () => route() }, 'Try again'),
        h('a', { class: 'linkbtn', href: '#/' }, 'Back to the library')));
  });
}

// ---- hosted account data (cached so it still opens offline)
const CACHE_KEY = 'sprig.cloudcache';
function loadCloudCache() {
  try {
    const c = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
    const u = cloud.currentUser();
    if (c && u && c.uid === u.id) { lib.me = c.me; lib.cloud = c.rows; lib.libPhotos = c.libPhotos || {}; lib.avatars = c.avatars || {}; }
  } catch { /* no cache */ }
}
function saveCloudCache() {
  if (!lib.me) return;
  try { localStorage.setItem(CACHE_KEY, JSON.stringify({ uid: lib.me.id, me: lib.me, rows: lib.cloud, libPhotos: lib.libPhotos, avatars: lib.avatars })); } catch { /* full */ }
}
function clearCloud() {
  lib.me = null; lib.cloud = []; lib.libPhotos = {}; lib.avatars = {};
  try { localStorage.removeItem(CACHE_KEY); } catch { /* ignore */ }
  rebuild();
}
async function refreshCloud() {
  if (!cloud.isSignedIn()) { clearCloud(); return; }
  try {
    const [me, rows] = await Promise.all([cloud.loadMe(), cloud.listRecipes()]);
    lib.me = me; lib.cloud = rows;
    try { lib.avatars = Object.fromEntries((await cloud.communityAvatars()).map((a) => [a.id, a.avatar])); } catch { /* keep the old ones */ }
    saveCloudCache();
  } catch (err) {
    if (!cloud.isSignedIn()) clearCloud();      // the session was no longer valid
    else if (!lib.me) loadCloudCache();         // offline: fall back to what we saved last time
  }
  rebuild();
  if (lib.me) await Promise.all([syncStars(), syncPlanner()]);   // independent of each other: no need to queue
}

// ---- stars follow the person between devices. This device pushes its list whenever it changes.
const SYNC_KEY = 'sprig.starsync';
const readSync = () => { try { return JSON.parse(localStorage.getItem(SYNC_KEY) || '{}'); } catch { return {}; } };
const writeSync = (v) => { try { localStorage.setItem(SYNC_KEY, JSON.stringify(v)); } catch { /* ignore */ } };
let pushTimer;
async function pushStars() {
  if (!lib.me) return;
  try {
    const row = await cloud.saveStars(starIds());
    writeSync({ uid: lib.me.id, at: row.updated_at, dirty: false });
    lib.syncError = '';
  } catch (err) { lib.syncError = err.status === 0 ? 'Offline. Will retry.' : err.message; }   // stays marked unsent; goes out next time
}
onStarsChange(() => {
  if (!lib.me) return;
  writeSync({ ...readSync(), uid: lib.me.id, dirty: true });
  clearTimeout(pushTimer);
  pushTimer = setTimeout(pushStars, 800);
});
async function syncStars() {
  try {
    const sync = readSync();
    const row = await cloud.loadUserData();
    if (row) { lib.libPhotos = row.library_photos || {}; saveCloudCache(); }
    if (sync.uid !== lib.me.id) {                         // first time this device meets this account: combine both
      if (row) addStars(row.stars);
      await pushStars();
    } else if (!row || sync.dirty) await pushStars();     // this device has unsent changes
    else if (row.updated_at !== sync.at) { replaceStars(row.stars); writeSync({ ...sync, at: row.updated_at }); }
    if (!lib.syncError || !/\boffline\b/i.test(lib.syncError)) lib.syncError = lib.syncError || '';
  } catch (err) { lib.syncError = err.status === 0 ? 'Offline. Will retry.' : err.message; }
}

// ---- the meal plan and shopping list follow the person too: one document, last change wins.
const PLAN_SYNC_KEY = 'sprig.plansync';
const readPlanSync = () => { try { return JSON.parse(localStorage.getItem(PLAN_SYNC_KEY) || '{}'); } catch { return {}; } };
const writePlanSync = (v) => { try { localStorage.setItem(PLAN_SYNC_KEY, JSON.stringify(v)); } catch { /* ignore */ } };
const planSyncMessage = (err) => (err.status === 0 ? 'Offline. Will retry.'
  : /planner/i.test(err.message || '') ? 'the database needs supabase/add_planner.sql' : err.message);
let planPushTimer;
async function pushPlanner() {
  if (!lib.me || !cloud.isSignedIn()) return;
  const sync = readPlanSync();
  const at = sync.at || Date.now();
  try {
    await cloud.savePlanner({ at, plan: planner.load(), shop: shop.load(), pantry: pantry.load(), collections: collections.load(), log: cooklog.load(), prices: prices.load() });
    const now = readPlanSync();
    if (now.at === at || !now.at) writePlanSync({ uid: lib.me.id, at, dirty: false });   // unless it changed again meanwhile
    lib.planSyncError = '';
  } catch (err) { lib.planSyncError = planSyncMessage(err); }
}
function plannerChanged() {
  if (!lib.me) return;   // signed out: stays on this device, and is offered to the account at the next sign-in
  writePlanSync({ uid: lib.me.id, at: Date.now(), dirty: true });
  clearTimeout(planPushTimer);
  planPushTimer = setTimeout(pushPlanner, 900);
}
planner.onChange(plannerChanged);
shop.onChange(plannerChanged);
pantry.onChange(plannerChanged);
collections.onChange(plannerChanged);
cooklog.onChange(plannerChanged);
prices.onChange(plannerChanged);
async function syncPlanner() {
  try {
    const sync = readPlanSync();
    const remote = await cloud.loadPlanner();
    const theirs = remote && typeof remote === 'object' && remote.at ? remote : null;
    const mine = { plan: planner.load(), shop: shop.load(), pantry: pantry.load(), collections: collections.load(), log: cooklog.load(), prices: prices.load() };
    const haveLocal = Object.keys(mine.plan.days).length > 0 || mine.shop.items.length > 0 || mine.shop.extras.length > 0
      || mine.pantry.have.length > 0 || mine.collections.length > 0 || Object.keys(mine.log).length > 0 || !prices.isEmpty(mine.prices);
    if (sync.uid !== lib.me.id) {
      // first time this device meets this account: keep both sides
      if (theirs) {
        planner.replace(planner.merge(theirs.plan, mine.plan));
        const s = shop.clean(theirs.shop);
        for (const i of mine.shop.items) if (!s.items.some((x) => x.id === i.id)) s.items.push(i);
        for (const x of mine.shop.extras) if (!s.extras.some((y) => y.text.toLowerCase() === x.text.toLowerCase())) s.extras.push(x);
        s.done = [...new Set([...s.done, ...mine.shop.done])];
        shop.replace(s);
        pantry.replace(pantry.merge(theirs.pantry, mine.pantry));
        collections.replace(collections.merge(theirs.collections, mine.collections));
        cooklog.replace(cooklog.merge(theirs.log, mine.log));
        if ('prices' in theirs) prices.replace(prices.merge(theirs.prices, mine.prices)); else prices.replace(mine.prices);
      }
      writePlanSync({ uid: lib.me.id, at: haveLocal || !theirs ? Date.now() : theirs.at, dirty: haveLocal });
      if (haveLocal) await pushPlanner();
    } else if (sync.dirty) await pushPlanner();          // this device has unsent changes
    else if (theirs && theirs.at !== sync.at) {          // another device changed it
      planner.replace(theirs.plan); shop.replace(theirs.shop);
      // a copy saved by an older version of the app has no pantry or collections: keep this device's
      if ('pantry' in theirs) pantry.replace(theirs.pantry);
      if ('collections' in theirs) collections.replace(theirs.collections);
      if ('log' in theirs) cooklog.replace(theirs.log);
      if ('prices' in theirs) prices.replace(theirs.prices);
      writePlanSync({ uid: lib.me.id, at: theirs.at, dirty: false });
      if (['plan', 'shop', 'pantry', 'collection', 'cooked', 'prices'].includes(document.body.dataset.view)) route();
    }
    if (!readPlanSync().dirty) lib.planSyncError = '';
  } catch (err) { lib.planSyncError = planSyncMessage(err); }
}

const restaurantName = (id) => {
  const m = (lib.me?.memberships || []).find((x) => x.restaurant?.id === id);
  return m?.restaurant.name || lib.restaurants.find((x) => x.id === id)?.name || 'Restaurant';
};
/** Where a cloud row shows up in the app. */
function cloudSource(row) {
  const mineRow = row.owner_id === lib.me?.id;
  if (row.scope === 'restaurant') return 'collection';
  if (row.scope === 'community') return mineRow && row.status !== 'approved' ? 'shared' : 'community';
  return 'account';
}
const SOURCE_GROUP = { base: 'library', edited: 'library', mine: 'mine', account: 'mine', shared: 'mine', community: 'community', collection: 'collection' };
const canEdit = (r) => !['community', 'collection', 'shared'].includes(r.source) || lib.me?.role === 'admin';

// ---- photos: cloud recipes keep theirs in recipes.photo; built-in library recipes in the person's own list
const isLibrary = (r) => r.source === 'base' || r.source === 'edited';
const photoOf = (r) => (r.cloud ? r.row.photo : (lib.me && isLibrary(r) ? lib.libPhotos[r.id] : null)) || null;
const canPhoto = (r) => !!lib.me && cloud.isSignedIn() && (r.cloud ? (r.source === 'account' || lib.me.role === 'admin') : isLibrary(r));
/** True while any recipe or library entry still uses this file (a shared Community copy can use the same photo). */
const photoInUse = (path) => lib.cloud.some((x) => x.photo === path) || Object.values(lib.libPhotos).includes(path);
/** After a change, delete the old file if it is this person's and nothing uses it any more. */
async function tidyPhoto(path) {
  if (!path || !lib.me) return;
  const mine = path.startsWith(`recipes/${lib.me.id}/`) || path.startsWith(`library/${lib.me.id}/`);
  if (mine && !photoInUse(path)) await photos.discard([path]);
}
async function setLibraryPhotos(map) {
  await cloud.saveLibraryPhotos(map);
  lib.libPhotos = map;
  saveCloudCache();
}
async function setPhoto(r, file) {
  const old = photoOf(r);
  const path = await photos.upload(r.cloud ? 'recipes' : 'library', file);
  try {
    if (r.cloud) { await cloud.setRecipePhoto(r.id, path); await refreshCloud(); }
    else await setLibraryPhotos({ ...lib.libPhotos, [r.id]: path });
  } catch (err) { await photos.discard([path]); throw err; }
  await tidyPhoto(old);
}
async function clearPhoto(r) {
  const old = photoOf(r);
  if (r.cloud) { await cloud.setRecipePhoto(r.id, null); await refreshCloud(); }
  else { const m = { ...lib.libPhotos }; delete m[r.id]; await setLibraryPhotos(m); }
  await tidyPhoto(old);
}
// list thumbnails load only when they scroll into view
const thumbObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    thumbObserver.unobserve(e.target);
    const el = e.target;
    photos.photoURL(el.dataset.photo).then((u) => { if (u) { el.style.backgroundImage = `url("${u}")`; el.classList.add('pic'); el.textContent = ''; } });
  }
}, { rootMargin: '300px' }) : null;
function thumb(r) {
  const t = tile(r.categories);
  const path = photoOf(r);
  if (path && thumbObserver) { t.dataset.photo = path; thumbObserver.observe(t); }
  return t;
}

function rebuild() {
  const map = new Map(lib.base.map((r) => [r.id, r]));
  for (const r of lib.more) if (!map.has(r.id)) map.set(r.id, r);     // the rest of the library, fetched on demand
  // A record that is not the shape the app expects (a damaged backup, or a row someone wrote to
  // the hosted database by hand) is skipped, so one bad recipe can never take the whole app down.
  const read = (rec, source) => {
    try {
      if (typeof rec.title !== 'string' || !Array.isArray(rec.ings)) throw new TypeError('not a recipe record');
      const r = fromRecord({ ...rec, categories: (Array.isArray(rec.categories) ? rec.categories : []).filter((c) => typeof c === 'string'),
        tags: (Array.isArray(rec.tags) ? rec.tags : []).filter((t) => typeof t === 'string'),
        yu: String(rec.yu ?? ''), yr: String(rec.yr ?? ''), dir: String(rec.dir ?? ''),
        ings: rec.ings.filter(Array.isArray).map(([q, raw, unit, item, group]) => [q, String(raw ?? ''), String(unit ?? ''), String(item ?? ''), String(group ?? '')]).filter(([q, raw, , item]) => q || raw || item) }, source);
      return r;
    } catch (err) { console.warn('Skipped a recipe that could not be read:', rec?.id, err); return null; }
  };
  const builtIn = new Set(map.keys());
  for (const rec of lib.mine.values()) {
    if (rec.deleted) { map.delete(rec.id); continue; }
    const r = read(rec, builtIn.has(rec.id) ? 'edited' : 'mine');
    if (r) map.set(rec.id, r);
  }
  for (const row of lib.cloud) {
    if (row.scope === 'private' && row.owner_id !== lib.me?.id) continue;          // admins can read these; the app never lists them
    const src = cloudSource(row);
    const r = read({ ...(row.body && typeof row.body === 'object' ? row.body : {}), id: row.id, title: row.title, categories: row.categories || [] }, src);
    if (!r) continue;
    r.cloud = true; r.row = row;
    r.hidden = row.scope === 'community' && row.status !== 'approved' && row.owner_id !== lib.me?.id;   // pending items from others live in Admin tools
    map.set(row.id, r);
  }
  lib.byId = map;
  lib.all = [...map.values()].filter((r) => !r.hidden).sort((a, b) => collator.compare(a.title, b.title));
  const cats = new Map();
  for (const r of lib.all) {
    r._hay = [r.title, r.categories.join(' '), (r.tags || []).join(' '), r.ings.map((i) => i.item).join(' '), r.dir].join('\n').toLowerCase();
    r._title = r.title.toLowerCase();
    for (const c of r.categories) {
      const k = c.toLowerCase();
      if (!cats.has(k)) cats.set(k, { name: c, n: 0 });
      cats.get(k).n++;
    }
  }
  lib.cats = [...cats.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}

async function saveRecord(rec) {
  await store.put(rec);
  lib.mine.set(rec.id, rec);
  rebuild();
}
async function dropRecord(id) {
  await store.remove(id);
  lib.mine.delete(id);
  rebuild();
}

function matches(q, cat, src = '') {
  const tokens = q.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const out = [];
  for (const r of lib.all) {
    if (src && SOURCE_GROUP[r.source] !== src) continue;
    if (cat && !r.categories.some((c) => c.toLowerCase() === cat.toLowerCase())) continue;
    if (tokens.every((t) => r._hay.includes(t))) out.push(r);
  }
  if (tokens.length) { // titles that contain every word first
    const inTitle = (r) => tokens.every((t) => r._title.includes(t));
    return [...out.filter(inTitle), ...out.filter((r) => !inTitle(r))];
  }
  return out;
}

// -------------------------------------------------------------------- views

const listState = { q: '', sec: -1, cat: '', src: '', shown: PAGE, scroll: 0 };
let onScroll = null;
let releaseWake = null;

function clearView() {
  if (onScroll) { window.removeEventListener('scroll', onScroll); onScroll = null; }
  if (releaseWake) { releaseWake(); releaseWake = null; }
}

function setView(view, tab) {
  document.body.dataset.view = view;
  for (const a of document.querySelectorAll('#tabs a')) {
    if (a.dataset.tab === tab) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
}

function starButton(id, onChange) {
  const btn = h('button', { class: 'star', type: 'button' });
  const paintStar = () => {
    const on = isStarred(id);
    btn.setAttribute('aria-pressed', String(on));
    btn.setAttribute('aria-label', on ? 'Remove from starred' : 'Star this recipe');
    fill(btn, icon('star', { size: 26, fill: on }));
  };
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    const on = toggleStar(id);
    paintStar();
    if (on) { btn.classList.remove('pop'); void btn.offsetWidth; btn.classList.add('pop'); buzz(12); }
    toast(on ? 'Starred' : 'Removed from starred', 1400);
    onChange?.(on);
  });
  paintStar();
  return btn;
}

const firstName = () => (lib.me?.displayName || '').trim().split(/\s+/)[0] || '';

function badgeText(r) {
  switch (r.source) {
    case 'mine': case 'account': return 'Mine';
    case 'community': return r.row.owner_id === lib.me?.id ? 'Shared' : 'Community';
    case 'shared': return r.row.status === 'declined' ? 'Declined' : 'Awaiting approval';
    case 'collection': return restaurantName(r.row.restaurant_id);
    default: return 'Edited';
  }
}

function viewList(starredOnly = false) {
  setView('list', starredOnly ? 'starred' : 'list');
  const input = h('input', {
    type: 'search', placeholder: 'Search recipes or ingredients',
    value: listState.q, enterkeyhint: 'search', autocomplete: 'off', autocapitalize: 'off', 'aria-label': 'Search recipes',
  });
  const counts = new Map(lib.cats.map((c) => [c.name, c.n]));
  const known = new Set(SECTIONS.flatMap(([, groups]) => groups));
  const sections = SECTIONS.map(([name, groups]) => [name, groups.filter((g) => counts.has(g)).map((g) => [g, counts.get(g)])]);
  const extra = lib.cats.filter((c) => !known.has(c.name)).map((c) => [c.name, c.n]);
  if (extra.length) {
    const other = sections.find(([name]) => name === 'Other');
    if (other) other[1].push(...extra); else sections.push(['Other', extra]);
  }
  const visible = sections.map((s, i) => [...s, i]).filter(([, rows]) => rows.length);
  if (listState.cat && listState.sec < 0) {
    const hit = visible.find(([, rows]) => rows.some(([g]) => g === listState.cat));
    if (hit) listState.sec = hit[2];
  }

  const count = h('p', { class: 'count muted small' });
  const promo = h('div');
  const paintPromo = () => {
    const cols = COLLECTIONS.filter((c) => listState.cat === c.group || (!listState.cat && visible.some(([, rows, i]) => i === listState.sec && rows.some(([g]) => g === c.group))));
    fill(promo, !starredOnly && cols.map((c) => h('a', { class: 'promo card', href: `#/links/${c.id}` },
      h('span', { class: 'tile', 'aria-hidden': 'true', 'data-sec': 2 }, '🌱'),
      h('span', null, h('strong', null, `More vegan recipes from ${c.site}`), h('span', { class: 'muted small' }, `By ${c.author}. Opens on her website.`)))));
  };
  const ul = h('ul', { class: 'rows intro' });
  setTimeout(() => ul.classList.remove('intro'), 1200);
  const empty = h('div');
  const more = h('button', { class: 'more', onclick: () => { listState.shown += PAGE; paint(); } }, 'Show more');
  const groupsRow = h('div', { class: 'chips groups', role: 'group', 'aria-label': 'Categories' });
  let results = [];

  const secButtons = [];
  const allBtn = h('button', { class: 'chip', type: 'button', onclick: () => { listState.sec = -1; listState.cat = ''; listState.shown = PAGE; chipState(); paint(); } }, 'All');
  secButtons.push([-1, allBtn]);
  const secRow = h('div', { class: 'chips', role: 'group', 'aria-label': 'Kinds of recipe' }, allBtn,
    visible.map(([name, , i]) => {
      const b = h('button', { class: 'chip', type: 'button', onclick: () => {
        listState.sec = listState.sec === i ? -1 : i; listState.cat = ''; listState.shown = PAGE; chipState(); paint();
      } }, name);
      secButtons.push([i, b]);
      return b;
    }));

  const srcLabels = [['', 'Everything'], ['library', 'Library'], ['mine', 'My recipes'], ['community', 'Community']];
  if (lib.cloud.some((x) => x.scope === 'restaurant')) srcLabels.push(['collection', 'Restaurant']);
  const srcButtons = srcLabels.map(([k, label]) => [k, h('button', { class: 'chip', type: 'button', onclick: () => {
    listState.src = k; listState.shown = PAGE; chipState(); paint();
  } }, label)]);
  const srcRow = h('div', { class: 'chips src', role: 'group', 'aria-label': 'Where recipes come from' }, srcButtons.map(([, b]) => b));
  srcRow.hidden = !lib.me;

  function chipState() {
    paintPromo();
    for (const [k, b] of srcButtons) b.setAttribute('aria-pressed', String(k === listState.src));
    for (const [i, b] of secButtons) b.setAttribute('aria-pressed', String(i === listState.sec));
    const sec = visible.find(([, , i]) => i === listState.sec);
    groupsRow.hidden = !sec;
    if (sec) {
      fill(groupsRow, sec[1].map(([g, n]) => h('button', {
        class: 'chip', type: 'button', 'aria-pressed': String(listState.cat === g),
        onclick: () => { listState.cat = listState.cat === g ? '' : g; listState.shown = PAGE; chipState(); paint(); },
      }, h('span', { class: 'e', 'aria-hidden': 'true' }, emojiFor(g)), g, ' ', h('span', { class: 'muted small' }, n.toLocaleString()))));
    }
  }

  function row(r, i = 0) {
    return h('li', { style: `--i:${Math.min(i, 14)}` },
      h('a', { class: 'rc', href: `#/r/${r.id}` },
        thumb(r),
        h('span', { class: 'txt' },
          h('span', { class: 't' }, r.title, r.source !== 'base' && h('span', { class: 'badge' }, badgeText(r))),
          h('span', { class: 'c' }, r.kind === 'link' ? `Link · ${r.src?.name || 'another website'} ↗`
            : r.categories.length ? r.categories.slice(0, 2).join(', ') : `${r.ings.length} ingredients`))),
      starButton(r.id));
  }

  function paint() {
    let pool = matches(listState.q, listState.cat, lib.me ? listState.src : '');
    if (starredOnly) pool = pool.filter((r) => isStarred(r.id));
    results = pool;
    const shown = results.slice(0, listState.shown);
    count.textContent = starredOnly
      ? `${results.length.toLocaleString()} starred`
      : results.length === lib.all.length ? `${results.length.toLocaleString()} recipes`
        : `${results.length.toLocaleString()} of ${lib.all.length.toLocaleString()} recipes`;
    ul.replaceChildren(...shown.map((r, i) => row(r, i)));
    more.hidden = shown.length >= results.length;
    if (results.length) { fill(empty); return; }
    const filtered = listState.q || listState.cat || (lib.me && listState.src);
    fill(empty, h('div', { class: 'empty' },
      h('span', { class: 'tile big', 'aria-hidden': 'true', 'data-sec': filtered ? 6 : 0 }, filtered ? '🔎' : '⭐'),
      h('h2', null, filtered ? 'Nothing matches' : 'Nothing starred yet'),
      h('p', { class: 'muted' }, filtered
        ? 'Try fewer words, or search by an ingredient like “lemon”.'
        : 'Tap the star on a recipe to keep it here for quick access.'),
      filtered
        ? h('button', { onclick: () => { listState.q = ''; listState.sec = -1; listState.cat = ''; listState.src = ''; input.value = ''; chipState(); paint(); } }, 'Clear search and filters')
        : h('button', { onclick: () => { location.hash = '#/'; } }, 'Browse recipes')));
  }

  const searchbar = h('div', { class: 'searchbar' }, h('label', { class: 'search' }, icon('search', { size: 22 }), input));
  let t;
  input.addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(() => { listState.q = input.value; listState.shown = PAGE; paint(); }, 120);
  });

  fill($app,
    band('hero',
      h('p', { class: 'eyebrow' }, starredOnly ? 'Your favorites' : `${greeting()}${firstName() ? `, ${firstName()}` : ''}`),
      h('h1', null, starredOnly ? 'Starred' : 'What are we cooking?'),
      h('p', { class: 'sub' }, starredOnly ? 'Your go-to recipes, one tap away.' : `${lib.all.length.toLocaleString()} recipes to search, scale and cook.`)),
    searchbar,
    !starredOnly && h('a', { class: 'promo card', href: '#/pantry' },
      h('span', { class: 'tile', 'aria-hidden': 'true', 'data-sec': 3 }, '🧺'),
      h('span', null, h('strong', null, 'What can I make?'), h('span', { class: 'muted small' }, 'Find recipes from what you have on hand.'))),
    starredOnly && (collections.load().length > 0 || cooklog.recent(cooklog.load()).length > 0) && h('div', { class: 'collrow' },
      h('h2', null, 'Collections'),
      h('div', { class: 'chips' },
        cooklog.recent(cooklog.load()).length > 0 && h('a', { class: 'chip', href: '#/cooked' }, 'Cooked', h('span', { class: 'muted' }, ` ${cooklog.recent(cooklog.load()).length}`)),
        collections.load().map((c) => h('a', { class: 'chip', href: `#/c/${c.id}` }, c.name, h('span', { class: 'muted' }, ` ${c.ids.length}`))))),
    !starredOnly && srcRow, !starredOnly && secRow, !starredOnly && groupsRow, promo, count, ul, empty, more);
  chipState();
  paint();
  window.scrollTo(0, listState.scroll);
  onScroll = () => { listState.scroll = window.scrollY; searchbar.classList.toggle('stuck', window.scrollY > 150); };
  window.addEventListener('scroll', onScroll, { passive: true });
}

function amountSplit(text) {
  const m = text.match(/^([\d¼½¾⅓⅔⅛⅜⅝⅞][\d\s/.\-–¼½¾⅓⅔⅛⅜⅝⅞]*)/);
  if (!m) return [text];
  const amt = m[1].trimEnd();
  return [h('b', null, amt), text.slice(amt.length)];
}

function tick(kids, extraClass = '') {
  const btn = h('button', { class: `tick ${extraClass}`.trim(), type: 'button', 'aria-pressed': 'false' }, kids);
  btn.addEventListener('click', () => { btn.setAttribute('aria-pressed', String(btn.getAttribute('aria-pressed') !== 'true')); buzz(6); });
  return btn;
}

function credit(r) {
  if (r.source === 'community') {
    const av = lib.avatars[r.row.owner_id] || (r.row.owner_id === lib.me?.id ? lib.me.avatar : null);
    return h('p', { class: 'credit' }, av && photos.photoImg(av, { class: 'avatar sm', alt: '' }),
      r.row.owner_id === lib.me?.id ? 'Shared by you' : `Shared by ${r.row.author_name || 'a chef'}`);
  }
  if (r.source === 'collection') return h('p', { class: 'credit' }, `From the ${restaurantName(r.row.restaurant_id)} collection`);
  if (r.source === 'shared') return h('p', { class: 'credit' }, r.row.status === 'declined'
    ? `Not approved${r.row.review_note ? `: ${r.row.review_note}` : '.'}` : 'Waiting for approval. Only you can see it until then.');
  return null;
}

/** "Recipe by Nora Taylor, Nora Cooks · View the original" for recipes that came from somewhere else. */
function sourceCredit(r) {
  const safe = (u) => (/^https?:\/\//i.test(u || '') ? u : '');
  if (hasSource(r)) {
    return h('p', { class: 'srccredit' },
      h('span', null, creditLine(r) || 'From another source'),
      safe(r.src.url) && h('a', { href: safe(r.src.url), target: '_blank', rel: 'noopener' }, 'View the original recipe'));
  }
  if (isAdapted(r)) {
    return h('p', { class: 'srccredit' },
      h('span', null, adaptedLine(r) || 'Adapted from another recipe'),
      safe(r.adapted.url) && h('a', { href: safe(r.adapted.url), target: '_blank', rel: 'noopener' }, 'See the original'));
  }
  return null;
}

/** The dish photo on the recipe page, with Add / Change / Remove when this person may change it. */
function photoBlock(r) {
  const path = photoOf(r);
  const allowed = canPhoto(r);
  if (!path && !allowed) return null;
  const box = h('div', { class: 'photo' });
  const choose = async () => {
    const file = await photos.pickPhoto();
    if (!file) return;
    fill(box, h('p', { class: 'muted small' }, 'Saving photo…'));
    try { await setPhoto(r, file); toast('Photo saved'); } catch (err) { toast(err.message, 4500); }
    route();
  };
  const drop = async () => {
    if (!await confirmDialog('Remove this photo?', 'Remove', true)) return;
    try { await clearPhoto(r); toast('Photo removed'); } catch (err) { toast(err.message, 4500); }
    route();
  };
  const note = isLibrary(r) && allowed ? h('span', { class: 'muted small' }, 'Only you can see this photo.') : null;
  if (!path) {
    fill(box, h('button', { type: 'button', class: 'addphoto', onclick: choose }, icon('camera'), 'Add a photo of your dish'), note);
    return box;
  }
  fill(box, photos.photoImg(path, { class: 'dish', alt: `Photo of ${r.title}` }),
    allowed && h('div', { class: 'row' },
      h('button', { type: 'button', onclick: choose }, 'Change photo'),
      h('button', { type: 'button', class: 'danger', onclick: drop }, 'Remove photo'),
      note));
  return box;
}

const RIGHTS = 'Share a copy of this recipe with the Community? Everyone signed in will be able to read it and see your name. Only share a recipe that is yours or that you have the right to share. Chef-owned or restaurant recipes should stay private. The administrator reviews every recipe before it appears, and you can withdraw it later.';

/** Share / withdraw buttons for the recipe page. */
const RIGHTS_LINK = 'Share a link to this recipe with the Community? People will see its name, who wrote it and a button that opens it on the original website. None of the recipe’s text is copied. The administrator reviews it before it appears, and you can withdraw it later.';

/** Start the person's own version of an imported recipe: ingredients kept, method rewritten in their words. */
function adaptRecipe(r) {
  viewEdit(null, {
    ...r, id: null, source: 'mine', title: `${r.title} (my version)`, dir: '', src: null,
    adapted: { ...r.src }, adaptFrom: r.dir, adapting: true,
  });
}

function sharing(r) {
  if (!lib.me) return null;
  const out = h('div', { class: 'stack' });
  const copy = lib.cloud.find((x) => x.scope === 'community' && x.source_recipe_id === r.id && x.owner_id === lib.me.id);
  const withdraw = (row) => h('button', { onclick: async () => {
    if (!await confirmDialog('Withdraw this recipe from the Community? Your own copy stays in your account.', 'Withdraw', true)) return;
    try { await cloud.deleteRecipe(row.id); await refreshCloud(); await tidyPhoto(row.photo); toast('Withdrawn'); route(); } catch (err) { toast(err.message, 4000); }
  } }, 'Withdraw from Community');
  const status = (row) => h('p', { class: 'muted small' }, row.status === 'approved'
    ? (row.body?.kind === 'link' ? 'A link to this recipe is in the Community.' : 'A copy of this recipe is in the Community.')
    : row.status === 'declined' ? `Not approved${row.review_note ? `: ${row.review_note}` : '.'}`
      : (row.body?.kind === 'link' ? 'A link to this recipe is waiting for approval.' : 'A copy is waiting for approval.'));
  if (r.source === 'account' && hasSource(r)) {
    const canLink = /^https?:\/\//i.test(r.src.url || '');
    fill(out,
      h('p', { class: 'muted small' }, 'This recipe came from another website, so its full text stays in your private recipes. To share it with the Community, share a link to the original, or make your own version in your own words.'),
      copy && [status(copy), withdraw(copy)],
      h('div', { class: 'row grow' },
        !copy && canLink && h('button', { onclick: async () => {
          if (!await confirmDialog(RIGHTS_LINK, 'Share link')) return;
          try { await cloud.shareLinkToCommunity(r.id); await refreshCloud(); toast('Link sent for approval'); route(); } catch (err) { toast(err.message, 4000); }
        } }, 'Share a link to the Community'),
        h('button', { onclick: () => adaptRecipe(r) }, 'Make my own version')));
  } else if (r.source === 'account') {
    if (copy) fill(out, status(copy), withdraw(copy));
    else fill(out, h('button', { onclick: async () => {
      if (!await confirmDialog(RIGHTS, 'Share')) return;
      try { await cloud.submitToCommunity(r.id); await refreshCloud(); toast('Sent for approval'); route(); } catch (err) { toast(err.message, 4000); }
    } }, 'Share with the Community'));
  } else if ((r.source === 'community' || r.source === 'shared') && r.row.owner_id === lib.me.id) fill(out, withdraw(r.row));
  else return null;
  return out;
}

/** A Community link card: name, credit and a button that opens the recipe on its own website. */
function viewLinkCard(r) {
  setView('recipe', 'list');
  const url = /^https?:\/\//i.test(r.src?.url || '') ? r.src.url : '';
  fill($app,
    h('div', { class: 'topbar' },
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => goBack('#/') }, icon('back')),
      h('span', { class: 'sp' }),
      starButton(r.id)),
    h('div', { class: 'rhead' }, tile(r.categories, true), h('h1', null, r.title)),
    r.categories.length > 0 && h('div', { class: 'labels' }, r.categories.map((c) => h('span', { class: 'label' }, c))),
    credit(r),
    h('div', { class: 'card stack linkcard' },
      h('p', null, h('strong', null, creditLine(r) || 'A recipe from another website')),
      h('p', { class: 'muted small' }, `This is a link to a recipe on ${r.src?.name || 'another website'}. Open it there to cook from it. The author keeps the visit and the credit.`),
      url && h('a', { class: 'linkbtn primary', href: url, target: '_blank', rel: 'noopener' }, `Open the recipe on ${r.src?.name || 'their website'} ↗`)),
    h('section', { class: 'tools stack' }, sharing(r)));
  window.scrollTo(0, 0);
}

function viewRecipe(id, preset = null) {
  const shared = !!preset;   // a recipe opened from a share link: not in the library, so nothing here that needs an id
  const r = preset || lib.byId.get(id);
  if (!r) return viewMissing();
  if (r.stub) return viewFetching(id, () => viewRecipe(id));
  if (r.kind === 'link') return viewLinkCard(r);
  setView('recipe', 'list');
  let factor = new Frac(1n);
  let smart = true;

  const factorIn = h('input', { type: 'number', inputmode: 'decimal', step: '0.25', min: '0.01', value: '1', 'aria-label': 'Multiplier' });
  const servIn = h('input', {
    type: 'number', inputmode: 'decimal', step: '1', min: '0.01', 'aria-label': 'Servings to make',
    disabled: !(r.yq && r.yq.n > 0n), value: r.yq ? num(r.yq, 2) : '',
  });
  const smartIn = h('input', { type: 'checkbox', checked: true, onchange: () => { smart = smartIn.checked; paint(); } });
  // Units: as written, or converted (volume to volume, weight to weight). Remembered between recipes.
  let units = '';
  try { units = localStorage.getItem(UNITS_KEY) || ''; } catch { /* private mode */ }
  if (!['', 'us', 'metric'].includes(units)) units = '';
  const unitsIn = h('select', { 'aria-label': 'Units', value: units, onchange: () => {
    units = unitsIn.value;
    try { localStorage.setItem(UNITS_KEY, units); } catch { /* private mode */ }
    paint();
  } }, h('option', { value: '' }, 'As written'), h('option', { value: 'us' }, 'US (cups, oz)'), h('option', { value: 'metric' }, 'Metric (ml, g)'));
  /** The recipe as shown: scaled, then in the chosen units. */
  const shown = () => {
    const res = scaleRecipe(r, factor, smart);
    return units ? { ...res, recipe: convertRecipe(res.recipe, units) } : res;
  };
  const ingBox = h('div');
  const dirBox = h('div');
  const cc = recipeCosting({ h, fill, scaled: () => shown().recipe, recipeId: shared ? null : r.id });
  const yieldLabel = r.yu || (r.yq ? '' : 'servings');

  const presets = [['½×', new Frac(1n, 2n)], ['1×', new Frac(1n)], ['2×', new Frac(2n)], ['3×', new Frac(3n)]]
    .map(([label, f]) => [f, h('button', { type: 'button', onclick: () => setFactor(f) }, label)]);

  function setFactor(f, source) {
    factor = f;
    if (source !== 'factor') factorIn.value = num(f, 3);
    if (source !== 'servings' && r.yq) servIn.value = num(f.mul(r.yq), 2);
    paint();
  }
  factorIn.addEventListener('input', () => {
    const v = parseFloat(factorIn.value);
    if (v > 0) setFactor(Frac.parse(trim0(v.toFixed(3))), 'factor');
  });
  servIn.addEventListener('input', () => {
    const v = parseFloat(servIn.value);
    if (v > 0 && r.yq) setFactor(factorForServings(r, Frac.parse(trim0(v.toFixed(2)))), 'servings');
  });
  const stepServings = (dir) => {
    if (!r.yq) return;
    const cur = parseFloat(servIn.value) || r.yq.toNumber();
    const next = Math.max(1, dir > 0 ? Math.floor(cur + 1e-9) + 1 : Math.ceil(cur - 1e-9) - 1);
    setFactor(factorForServings(r, Frac.parse(String(next))), null);
  };

  function paint() {
    const { recipe: s, warnings } = shown();
    for (const [f, b] of presets) b.setAttribute('aria-pressed', String(f.eq(factor)));
    const groups = [];
    for (const ing of s.ings) {
      let g = groups[groups.length - 1];
      if (!g || g.name !== ing.group) groups.push((g = { name: ing.group, items: [] }));
      g.items.push(ing);
    }
    const y = formatYield(s);
    const steps = s.dir ? s.dir.split('\n').filter((l) => l.trim()) : [];
    fill(ingBox,
      h('div', { class: 'facts' },
        y && h('span', null, h('strong', null, 'Makes '), y),
        s.ings.length > 0 && h('span', null, h('strong', null, s.ings.length), s.ings.length === 1 ? ' ingredient' : ' ingredients')),
      s.ings.length > 0 && h('h2', null, 'Ingredients'),
      groups.map((g) => [g.name && h('h3', null, g.name),
        h('ul', { class: 'ing' }, g.items.map((i) => h('li', null,
          tick([h('span', { class: 'box' }, icon('check', { size: 16 })), h('span', { class: 'what' }, amountSplit(formatIngredient(i)))]))))]));
    fill(dirBox,
      steps.length > 0 && h('h2', null, 'Method'),
      steps.length > 0 && h('button', { class: 'cookbtn', type: 'button', onclick: cookMode }, icon('play', { size: 20 }), 'Start cook mode'),
      steps.length > 1
        ? h('ol', { class: 'steps', onclick: (e) => {
          const ol = e.currentTarget;
          if (e.target.closest('.tick') && ol.querySelectorAll('.tick[aria-pressed=true]').length === steps.length) celebrate(e.target);
        } }, steps.map((l, n) => h('li', null,
          tick([h('span', { class: 'n' }, n + 1), h('span', { class: 'what' }, l)]), timerChips(l))))
        : steps.length === 1 && h('div', { class: 'dir' }, h('p', null, steps[0]), timerChips(steps[0])),
      warnings.length > 0 && h('p', { class: 'note' }, warnings.join(' ')));
    cc.paint();
  }

  // keep the screen awake while cooking
  let sentinel = null;
  let awake = false;
  const awakeBtn = h('button', { class: 'icon-btn', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Keep screen on while cooking', title: 'Keep screen on while cooking', hidden: !('wakeLock' in navigator), onclick: () => setWake(!awake) }, icon('sun'));
  async function acquire() {
    try { sentinel = await navigator.wakeLock.request('screen'); } catch { awake = false; awakeBtn.setAttribute('aria-pressed', 'false'); toast('Could not keep the screen on'); }
  }
  const onVisible = () => { if (awake && document.visibilityState === 'visible') acquire(); };
  function setWake(on) {
    awake = on;
    awakeBtn.setAttribute('aria-pressed', String(on));
    if (on) { acquire(); document.addEventListener('visibilitychange', onVisible); toast('Screen will stay on', 1800); }
    else { sentinel?.release().catch(() => {}); sentinel = null; document.removeEventListener('visibilitychange', onVisible); }
  }
  releaseWake = () => setWake(false);

  // one step at a time, big text, swipe or tap to move on
  function cookMode() {
    const s = shown().recipe;
    const steps = s.dir ? s.dir.split('\n').filter((l) => l.trim()) : [];
    if (!steps.length) return;
    let i = 0;
    const wasAwake = awake;
    if (!wasAwake && 'wakeLock' in navigator) setWake(true);
    const num = h('p', { class: 'cook-n' });
    const text = h('p', { class: 'cook-text', 'aria-live': 'polite' });
    const chips = h('div');
    const bar = h('div', { class: 'cook-bar', 'aria-hidden': 'true' }, steps.map(() => h('i')));
    const back = h('button', { type: 'button', onclick: () => go(-1) }, 'Back');
    const next = h('button', { class: 'primary', type: 'button', onclick: () => go(1) });
    const body = h('div', { class: 'cook-body' }, num, text, chips);
    let sheet = null;

    const closeBtn = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close cook mode', onclick: close }, icon('close'));
    const ingBtn = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Show ingredients', onclick: () => {
      if (sheet) { sheet.remove(); sheet = null; return; }
      sheet = h('div', { class: 'cook-sheet' },
        h('h2', null, 'Ingredients'),
        h('ul', null, s.ings.map((ing) => h('li', null, amountSplit(formatIngredient(ing))))),
        h('button', { class: 'primary', type: 'button', style: 'margin-top:1.2rem;width:100%', onclick: () => { sheet.remove(); sheet = null; } }, 'Back to the step'));
      overlay.append(sheet);
    } }, icon('list'));
    const overlay = h('div', { class: 'cook', role: 'dialog', 'aria-modal': 'true', 'aria-label': `Cooking ${r.title}` },
      h('div', { class: 'cook-top' }, closeBtn, h('span', { class: 'ttl' }, r.title), ingBtn),
      bar, body, h('div', { class: 'cook-foot' }, back, next));

    function paintStep(dir = 1) {
      num.textContent = `Step ${i + 1} of ${steps.length}`;
      text.textContent = steps[i];
      text.className = `cook-text${dir < 0 ? ' back' : ''}`;
      text.style.animation = 'none'; void text.offsetWidth; text.style.animation = '';
      fill(chips, timerChips(steps[i]));
      [...bar.children].forEach((b, n) => b.classList.toggle('on', n <= i));
      back.disabled = i === 0;
      next.textContent = i === steps.length - 1 ? 'Done' : 'Next step';
    }
    function go(d) {
      if (i + d >= steps.length) { close(); celebrate(); return; }
      if (i + d < 0) return;
      i += d; paintStep(d); buzz(8);
    }
    function close() {
      overlay.remove();
      document.removeEventListener('keydown', onKey, true);
      if (!wasAwake) setWake(false);
    }
    function onKey(e) {
      if (e.key === 'Escape') { e.stopImmediatePropagation(); e.preventDefault(); if (sheet) { sheet.remove(); sheet = null; } else close(); }
      else if (e.key === 'ArrowRight' || e.key === ' ') { e.preventDefault(); go(1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
    }
    let x0 = 0; let y0 = 0;
    body.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    body.addEventListener('touchend', (e) => {
      const dx = e.changedTouches[0].clientX - x0; const dy = e.changedTouches[0].clientY - y0;
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
    }, { passive: true });
    document.addEventListener('keydown', onKey, true);
    document.body.append(overlay);
    paintStep();
    next.focus();
  }

  const copy = async () => {
    const text = recipeToText(shown().recipe);
    toast(await copyText(text) ? 'Recipe copied' : 'Could not copy on this browser');
  };
  const saveCopy = () => {
    const s = scaleRecipe(r, factor, smart).recipe;
    s.title = shared ? r.title : factor.eq(new Frac(1n)) ? `${r.title} (copy)` : `${r.title} (scaled)`;
    viewEdit(null, s);
  };

  // shopping list: adds this recipe at the scale on screen; pressing again takes it off
  const shopBtn = h('button', { type: 'button', onclick: () => {
    const on = shop.has(r.id);
    const ok = on ? shop.remove(r.id) : shop.add(r.id, factor);
    if (!ok) { toast('Could not save the shopping list on this browser'); return; }
    paintShop();
    toast(on ? 'Taken off the shopping list' : 'Added to the shopping list');
  } });
  const shopLink = h('a', { class: 'linkbtn', href: '#/shop' }, 'Open the shopping list');
  const planBtn = h('button', { type: 'button', onclick: async () => {
    const day = await pickDay(r.title);
    if (!day) return;
    if (!planner.add(day, { id: r.id, f: String(factor) })) { toast('Could not save the meal plan on this browser'); return; }
    toast(`Planned for ${day === planner.isoDate(new Date()) ? 'today' : DAY_FMT.format(planner.parseDate(day))}`);
  } }, 'Add to meal plan');
  const collBtn = h('button', { type: 'button', onclick: () => collectionsDialog(r, paintColl) });
  function paintColl() {
    const n = collections.load().filter((c) => c.ids.includes(r.id)).length;
    collBtn.textContent = n ? `Collections (${n})` : 'Add to a collection';
  }
  paintColl();
  function paintShop() {
    const on = shop.has(r.id);
    shopBtn.textContent = on ? '✓ On the shopping list' : 'Add to shopping list';
    shopBtn.setAttribute('aria-pressed', String(on));
    shopLink.hidden = !on;
  }
  paintShop();

  // your own record of this recipe: rating, when you made it, private notes
  const logBox = h('section', { class: 'mylog', 'aria-label': 'Your notes on this recipe' });
  const noteIn = h('textarea', { rows: '3', maxlength: '2000', placeholder: 'Private notes: use less salt, doubles well…', 'aria-label': 'Private notes' });
  noteIn.value = cooklog.get(r.id).note;
  let noteTimer;
  const saveNote = () => { clearTimeout(noteTimer); if (noteIn.value.trim() !== cooklog.get(r.id).note) cooklog.setNote(r.id, noteIn.value); };
  noteIn.addEventListener('input', () => { clearTimeout(noteTimer); noteTimer = setTimeout(saveNote, 900); });
  noteIn.addEventListener('blur', saveNote);
  function paintLog() {
    const e = cooklog.get(r.id);
    const { times, last } = cooklog.summary(e);
    const today = planner.isoDate(new Date());
    fill(logBox,
      h('h2', null, 'Your notes'),
      h('div', { class: 'ratingrow', role: 'group', 'aria-label': 'Your rating' }, [1, 2, 3, 4, 5].map((n) =>
        h('button', { class: 'ratestar', type: 'button', 'aria-pressed': String(e.rating >= n), 'aria-label': `${n} ${n === 1 ? 'star' : 'stars'}`,
          onclick: () => { cooklog.setRating(r.id, n); buzz(6); paintLog(); } }, icon('star', { size: 26, fill: e.rating >= n }))),
        h('span', { class: 'muted small' }, e.rating ? `${e.rating} of 5` : 'Not rated')),
      h('div', { class: 'row' },
        h('button', { type: 'button', class: e.made.includes(today) ? '' : 'primary', disabled: e.made.includes(today),
          onclick: () => { cooklog.markMade(r.id, today); celebrate(); paintLog(); } }, e.made.includes(today) ? '✓ Made today' : 'I made this'),
        h('span', { class: 'muted small madeline' }, times
          ? `Made ${times === 1 ? 'once' : `${times} times`}, last ${last === today ? 'today' : `on ${DATE_FMT.format(planner.parseDate(last))}`}`
          : 'Not made yet'),
        times > 0 && h('button', { class: 'linklike', type: 'button', onclick: () => { cooklog.unmarkLast(r.id); paintLog(); } }, 'Undo')),
      noteIn,
      h('p', { class: 'muted small' }, lib.me ? 'Only you see these. Saved with your account.' : 'Only you see these. Kept on this device.'));
  }
  paintLog();
  // leaving the recipe, closing the tab or switching apps: don't lose a note still being typed
  const prevRelease = releaseWake;
  window.addEventListener('pagehide', saveNote);
  document.addEventListener('visibilitychange', saveNote);
  releaseWake = () => {
    saveNote();
    window.removeEventListener('pagehide', saveNote);
    document.removeEventListener('visibilitychange', saveNote);
    prevRelease?.();
  };

  const [primary, ...rest] = r.categories;
  const sharedFrom = shared ? preset.sharedFrom : '';
  fill($app,
    band('rband',
      h('div', { class: 'topbar' },
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => goBack('#/') }, icon('back')),
        h('span', { class: 'sp' }),
        awakeBtn,
        !shared && starButton(r.id),
        !shared && canEdit(r) && h('a', { class: 'icon-btn', href: `#/edit/${r.id}`, 'aria-label': 'Edit recipe', title: 'Edit recipe' }, icon('edit'))),
      h('div', { class: 'rhead' }, tile(r.categories, true), h('h1', null, r.title)),
      r.categories.length > 0 && h('div', { class: 'labels' }, r.categories.map((c) => h('span', { class: 'label' }, c)))),
    shared ? sharedNote(sharedFrom) : photoBlock(r),
    credit(r),
    sourceCredit(r),
    h('div', { class: 'cols' },
      h('div', { class: 'side' },
    h('section', { class: 'dock', 'aria-label': 'Scale this recipe' },
          h('div', { class: 'seg' }, presets.map(([, b]) => b),
            h('label', { class: 'mult' }, h('span', { 'aria-hidden': 'true' }, '×'), factorIn)),
          r.yq
            ? h('div', { class: 'makes' },
              h('span', { class: 'lbl' }, 'Makes'),
              h('button', { class: 'step', type: 'button', 'aria-label': 'Fewer servings', onclick: () => stepServings(-1) }, icon('minus')),
              servIn,
              h('button', { class: 'step', type: 'button', 'aria-label': 'More servings', onclick: () => stepServings(1) }, icon('plus')),
              h('span', { class: 'lbl' }, yieldLabel))
            : h('p', { class: 'note', style: 'margin:.5rem .3rem .1rem' }, 'No yield is listed, so scale with the multiplier.')),
        ingBox),
      dirBox),
    cc.nutri,
    cc.cost,
    !shared && logBox,
    h('section', { class: 'tools stack' },
      h('label', { class: 'check' }, smartIn, 'Smart units (8 Tbsp becomes ½ cup)'),
      h('label', { class: 'unitpick' }, h('span', null, 'Units'), unitsIn),
      shared
        ? h('div', { class: 'row grow' }, h('button', { class: 'primary', onclick: saveCopy }, 'Save to my recipes'))
        : h('div', { class: 'row grow' }, planBtn, collBtn, r.ings.length > 0 && shopBtn, r.ings.length > 0 && shopLink),
      h('div', { class: 'row grow' },
        h('button', { onclick: copy }, 'Copy'),
        !shared && h('button', { onclick: () => shareDialog(r) }, 'Share link'),
        !shared && h('button', { onclick: saveCopy }, 'Save scaled copy'),
        h('button', { onclick: () => window.print() }, 'Print card')),
      !shared && sharing(r),
      r.tags && r.tags.length > 0 && h('p', { class: 'muted small' }, 'Original labels: ', r.tags.join(', '))),
    h('p', { class: 'printfoot' }, 'Sprig'));
  paint();
  window.scrollTo(0, 0);
}

/** "Shared with you" strip on a recipe opened from a link. */
function sharedNote(from) {
  return h('p', { class: 'srccredit sharednote' }, h('span', null, from ? `Shared with you by ${from}` : 'Shared with you'),
    h('a', { href: '#/' }, 'Open the recipe library'));
}

/** Send a recipe as a link (with a QR code for showing it in person). */
async function shareDialog(r) {
  const link0 = hasSource(r) && /^https?:\/\//i.test(r.src.url || '') ? r.src.url : '';
  if (hasSource(r) && !link0) { toast('This recipe has no web address to share. Use Copy to send the text.', 4000); return; }
  let link = link0;
  if (!link) {
    try { link = linkFor(await packRecipe(toRecord(r), lib.me?.displayName || '')); } catch { toast('Could not make a link for this recipe'); return; }
  }
  const msg = `${r.title}: ${link}`;
  const box = h('div', { class: 'qr big' });
  let qr = link.length <= 700;   // longer links make a code too dense for a phone camera
  if (qr) { try { box.innerHTML = qrSvg(link, { label: `QR code for ${r.title}` }); } catch { qr = false; } }
  const dlg = h('dialog', { class: 'qrdialog sharedialog' },
    h('h2', null, link0 ? 'Share the original recipe' : 'Share this recipe'),
    h('p', { class: 'muted small' }, link0
      ? 'This recipe is from another website, so the link goes to the original and the author gets the visit.'
      : `Anyone with the link can read this copy and save it to their own recipes. Later changes you make are not sent.${qr ? '' : ' This recipe is too long for a QR code, so send the link.'}`),
    qr && box,
    h('input', { class: 'full link', readonly: true, value: link, 'aria-label': 'Recipe link', onfocus: (e) => e.target.select() }),
    h('div', { class: 'row' },
      h('button', { class: 'primary', onclick: async () => toast(await copyText(link) ? 'Link copied' : 'Could not copy. Press and hold the link to copy it.', 3000) }, 'Copy link'),
      navigator.share && h('button', { onclick: () => navigator.share({ title: r.title, text: msg }).catch(() => {}) }, 'Share…'),
      h('a', { class: 'btnlink', href: `mailto:?subject=${encodeURIComponent(r.title)}&body=${encodeURIComponent(msg)}` }, 'Email'),
      h('button', { onclick: () => dlg.close() }, 'Done')));
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

/** A recipe from a share link (#/s/…). */
async function viewShared(payload) {
  setView('recipe', 'list');
  fill($app, pageHead('Opening the recipe…'));
  let got;
  try {
    got = await unpackRecipe(payload);
    const r = fromRecord(got.rec, 'link-share');
    r.sharedFrom = got.from;
    if (location.hash.replace(/^#\/?/, '').split('/')[1] !== payload) return;   // they moved on while it was unpacking
    viewRecipe(r.id, r);
  } catch (err) {
    if (location.hash.replace(/^#\/?/, '').split('/')[1] !== payload) return;
    fill($app, pageHead('That link did not work'),
      h('p', null, /update it/.test(err.message) ? err.message : 'The recipe link looks damaged or cut short. Ask for it to be sent again, and make sure the whole link was copied.'),
      h('a', { class: 'linkbtn', href: '#/' }, 'Open the recipe library'));
  }
}

function viewEdit(id, template) {
  setView('edit', 'new');
  const existing = id ? lib.byId.get(id) : null;
  if (id && !existing) return viewMissing();
  if (existing?.stub) return viewFetching(id, () => viewEdit(id));
  if (existing && !canEdit(existing)) { fill($app, pageHead('Read only'), h('p', { class: 'muted' }, 'This recipe belongs to someone else. Open it and use “Save scaled copy” to make your own version.'), h('p', null, h('a', { href: `#/r/${existing.id}` }, 'Back to the recipe'))); return; }
  const r = existing || template || { title: '', categories: [], tags: [], yq: null, yu: '', yr: '', dir: '', ings: [], source: 'mine' };

  const title = h('input', { class: 'full', value: r.title, autocomplete: 'off', 'aria-label': 'Title' });
  const cats = h('input', { class: 'full', value: r.categories.join(', '), placeholder: 'e.g. Soups, Main dish', 'aria-label': 'Categories' });
  const yld = h('input', { class: 'full', value: formatYield(r) || r.yr, placeholder: 'e.g. 4 servings, 24 cookies', 'aria-label': 'Yield' });
  const dir = h('textarea', { 'aria-label': 'Directions', placeholder: 'Directions. Leave a blank line between paragraphs.' });
  dir.value = r.dir;
  const adapting = !!r.adapting;
  const src0 = r.src || {};
  const srcAuthor = h('input', { class: 'full', value: src0.author || '', placeholder: 'e.g. Nora Taylor (blank if it’s yours)', autocomplete: 'off', 'aria-label': 'Recipe by' });
  const srcName = h('input', { class: 'full', value: src0.name || '', placeholder: 'Website, book or person, e.g. Nora Cooks', autocomplete: 'off', 'aria-label': 'From' });
  const srcUrl = h('input', { class: 'full', type: 'url', value: src0.url || '', placeholder: 'https://…', autocomplete: 'off', autocapitalize: 'off', 'aria-label': 'Link to the original' });
  const rowsBox = h('div');
  const datalist = h('datalist', { id: 'units' }, UNIT_CHOICES.filter(Boolean).map((u) => h('option', { value: u })));

  function addRow(vals = { amount: '', unit: '', item: '', group: '' }, focus = false) {
    const amount = h('input', { class: 'amt', value: vals.amount, placeholder: 'Amt', inputmode: 'text', 'aria-label': 'Amount' });
    const unit = h('input', { class: 'unit', value: vals.unit, placeholder: 'Unit', list: 'units', autocapitalize: 'off', 'aria-label': 'Unit' });
    const item = h('input', { class: 'item', value: vals.item, placeholder: 'Ingredient', 'aria-label': 'Ingredient' });
    const grp = h('input', { class: 'grp', value: vals.group, placeholder: 'Group (optional, e.g. Sauce)', 'aria-label': 'Group' });
    const row = h('div', { class: 'card ing-row' },
      h('div', { class: 'row' }, amount, unit), item, grp,
      h('div', { class: 'rowtools' },
        h('button', { type: 'button', 'aria-label': 'Move up', onclick: () => row.previousElementSibling && row.previousElementSibling.before(row) }, '↑'),
        h('button', { type: 'button', 'aria-label': 'Move down', onclick: () => row.nextElementSibling && row.nextElementSibling.after(row) }, '↓'),
        h('button', { type: 'button', class: 'danger', onclick: () => row.remove() }, 'Remove')));
    row._get = () => [amount.value, unit.value, item.value, grp.value];
    rowsBox.append(row);
    if (focus) amount.focus();
  }
  for (const i of r.ings) addRow({ amount: amountForEditing(i), unit: i.unit, item: i.item, group: i.group });
  if (!r.ings.length) addRow();

  async function save() {
    if (!title.value.trim()) { toast('Please give the recipe a title'); title.focus(); return; }
    const ings = [...rowsBox.children].map((row) => ingredientFromFields(...row._get())).filter(Boolean);
    const text = yld.value.trim();
    const [yq, yu] = text ? parseYield(text) : [null, ''];
    const recipe = {
      id: existing ? existing.id : `u-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      title: title.value.trim(), categories: splitCategories(cats.value), tags: (existing || template || {}).tags || [], yq, yu, yr: text,
      dir: dir.value.trim(), ings,
      src: { author: srcAuthor.value.trim(), name: srcName.value.trim(), url: srcUrl.value.trim() },
    };
    if (recipe.src.url && !/^https?:\/\//i.test(recipe.src.url)) recipe.src.url = `https://${recipe.src.url}`;
    const base = existing || template || {};
    if (isAdapted(base)) recipe.adapted = { ...base.adapted };
    if (adapting) {
      if (!recipe.dir) { toast('Write the method in your own words first'); dir.focus(); return; }
      if (wordingOverlap(recipe.dir, base.adaptFrom) > MAX_OVERLAP) {
        toast('Your method is still too close to the original wording. Rewrite the steps in your own words.', 5000);
        dir.focus();
        return;
      }
    }
    const rec = toRecord(recipe);
    let target = recipe.id;
    if ((existing && existing.cloud) || (!existing && lib.me && cloud.isSignedIn())) {
      try {
        if (existing) await cloud.updateRecipe(existing.id, rec);
        else target = (await cloud.createRecipe(rec)).id;
        await refreshCloud();
      } catch (err) {
        if (err.status !== 0 || existing) { toast(err.message, 4500); return; }
        await saveRecord(rec);                                   // offline: keep it on this device
        toast('You are offline, so this was saved on this device only.', 4500);
      }
    } else await saveRecord(rec);
    toast('Saved');
    location.replace(`${location.pathname}${location.search}#/r/${target}`);
  }

  async function del() {
    const mine = existing.source === 'mine' || existing.cloud;
    const ok = await confirmDialog(
      mine ? `Delete "${existing.title}"?` : `Remove "${existing.title}" from your library? You can restore it later in Settings.`,
      mine ? 'Delete' : 'Remove', true);
    if (!ok) return;
    if (existing.cloud) {
      try { await cloud.deleteRecipe(existing.id); await refreshCloud(); await tidyPhoto(existing.row.photo); } catch (err) { toast(err.message, 4500); return; }
    } else if (mine) await dropRecord(existing.id);
    else await saveRecord({ id: existing.id, deleted: true });
    toast('Removed');
    location.replace(`${location.pathname}${location.search}#/`);
  }
  async function revert() {
    if (!await confirmDialog(`Discard your edits to "${existing.title}" and go back to the original?`, 'Revert')) return;
    await dropRecord(existing.id);
    toast('Reverted to original');
    location.replace(`${location.pathname}${location.search}#/r/${existing.id}`);
  }

  fill($app, 
    pageHead(existing ? 'Edit recipe' : adapting ? 'Make your own version' : template?.imported ? 'Check and save' : template ? 'Save as new recipe' : 'New recipe'),
    !existing && !template && h('p', { class: 'row grow' }, h('a', { class: 'linkbtn', href: '#/import' }, '⤓ Import a recipe from a web page'),
      h('a', { class: 'linkbtn', href: '#/transfer' }, '⤓ Import files (Paprika, Mealie…)')),
    adapting && h('p', { class: 'muted' }, 'Keep or change the ingredients, then write the method in your own words. Your version can be shared with the Community and will say “Adapted from” with a link to the original.'),
    h('label', { class: 'field' }, h('span', null, 'Title'), title),
    h('label', { class: 'field' }, h('span', null, 'Categories'), cats),
    h('label', { class: 'field' }, h('span', null, 'Yield'), yld),
    h('h2', null, 'Ingredients'),
    h('p', { class: 'muted small' }, 'Amounts can be 2, 1/2, 1 1/2, 1.5 or ½. Use Group for headings like Sauce or Topping.'),
    datalist, rowsBox,
    h('button', { type: 'button', class: 'full', onclick: () => addRow(undefined, true) }, '+ Add ingredient'),
    adapting && r.adaptFrom && h('details', { class: 'card original' },
      h('summary', null, 'The original method, for reference'),
      h('p', { class: 'muted small' }, 'Write your own steps below in your own words. Don’t copy these. Change what you like: technique, timing, seasoning.'),
      h('ol', null, r.adaptFrom.split('\n').filter((l) => l.trim()).map((l) => h('li', null, l)))),
    h('label', { class: 'field' }, h('span', null, adapting ? 'Your method, in your own words' : 'Directions'), dir),
    h('h2', null, 'Credit'),
    isAdapted(r)
      ? [h('p', { class: 'srccredit' }, h('span', null, adaptedLine(r) || 'Adapted from another recipe'),
        /^https?:\/\//i.test(r.adapted.url || '') && h('a', { href: r.adapted.url, target: '_blank', rel: 'noopener' }, 'See the original')),
      h('p', { class: 'muted small' }, 'This credit stays on your version, including in the Community.')]
      : [h('p', { class: 'muted small' }, 'For a recipe from someone else, say who wrote it and link to the original. It is shown on the recipe.'),
        h('label', { class: 'field' }, h('span', null, 'Recipe by'), srcAuthor),
        h('label', { class: 'field' }, h('span', null, 'From'), srcName),
        h('label', { class: 'field' }, h('span', null, 'Link to the original'), srcUrl)],
    h('div', { class: 'row grow' },
      h('button', { class: 'primary', onclick: save }, 'Save'),
      h('button', { onclick: () => (template ? route() : goBack(existing ? `#/r/${existing.id}` : '#/')) }, 'Cancel')),
    existing && h('div', { class: 'actions row grow' },
      existing.source === 'edited' && h('button', { onclick: revert }, 'Revert to original'),
      h('button', { class: 'danger', onclick: del }, existing.source === 'mine' || existing.cloud ? 'Delete recipe' : 'Remove from library')));
  window.scrollTo(0, 0);
  if (!existing && !template) title.focus();
}

// ------------------------------------------------------ outside collections and web import

/** Recipe titles from an outside author, each opening on their own website (nothing is copied). */
// ---- meal plan and shopping list: two pages under the Plan tab

const planSeg = (on) => h('div', { class: 'seg planseg', role: 'group', 'aria-label': 'Plan or shopping list' },
  h('a', { class: 'segbtn', href: '#/plan', 'aria-current': on === 'plan' ? 'page' : null }, 'Meal plan'),
  h('a', { class: 'segbtn', href: '#/shop', 'aria-current': on === 'shop' ? 'page' : null }, 'Shopping list'));

const timesLabel = (f) => (f.eq(new Frac(1n)) ? '' : `×${num(f, 2)}`);
const DAY_FMT = new Intl.DateTimeFormat(undefined, { weekday: 'long' });
const DATE_FMT = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });

/** Pick a recipe (or type a note) for a day of the meal plan. Resolves to a plan entry or null. */
function pickForPlan(dayLabel) {
  return new Promise((resolve) => {
    // settle at once on a choice; the dialog's own 'close' event (Esc, Cancel) can arrive late
    let settled = false;
    const done = (value) => { if (settled) return; settled = true; if (dlg.open) dlg.close(); dlg.remove(); resolve(value); };
    const search = h('input', { type: 'search', class: 'full', placeholder: 'Search recipes', 'aria-label': 'Search recipes', autocomplete: 'off' });
    const results = h('ul', { class: 'picklist' });
    const note = h('input', { type: 'text', class: 'full', maxlength: '80', placeholder: 'Or a note: Leftovers, Eating out…', 'aria-label': 'Note' });
    const dlg = h('dialog', { class: 'pickdialog', 'aria-labelledby': 'pick-title' },
      h('h2', { id: 'pick-title' }, `Add to ${dayLabel}`),
      search, results,
      h('form', { class: 'row', onsubmit: (e) => { e.preventDefault(); if (note.value.trim()) done({ note: note.value }); } },
        note, h('button', { type: 'submit' }, 'Add note')),
      h('div', { class: 'row' }, h('button', { type: 'button', onclick: () => done(null) }, 'Cancel')));
    function paint() {
      const q = search.value.trim();
      // nothing typed yet: starred recipes are the likeliest picks
      const found = (q ? matches(q, '') : lib.all.filter((r) => isStarred(r.id))).filter((r) => r.kind !== 'link').slice(0, 40);
      fill(results, found.length
        ? found.map((r) => h('li', null, h('button', { type: 'button', onclick: () => done({ id: r.id, f: '1' }) },
          h('span', { class: 'e', 'aria-hidden': 'true' }, emojiFor(r.categories[0])), r.title)))
        : h('li', { class: 'muted small' }, q ? 'No recipes match.' : 'Type to search, or star recipes to see them here.'));
    }
    search.addEventListener('input', paint);
    dlg.addEventListener('close', () => done(null));
    document.body.append(dlg);
    paint();
    dlg.showModal();
  });
}

/** Pick a day (today and the next two weeks) for a recipe. Resolves to 'YYYY-MM-DD' or null. */
function pickDay(title) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (value) => { if (settled) return; settled = true; if (dlg.open) dlg.close(); dlg.remove(); resolve(value); };
    const today = planner.isoDate(new Date());
    const plan = planner.load();
    const dlg = h('dialog', { class: 'pickdialog', 'aria-labelledby': 'day-title' },
      h('h2', { id: 'day-title' }, 'Which day?'),
      h('p', { class: 'muted small' }, title),
      h('ul', { class: 'picklist' }, Array.from({ length: 14 }, (_, n) => planner.addDays(today, n)).map((d) => {
        const n = (plan.days[d] || []).length;
        return h('li', null, h('button', { type: 'button', onclick: () => done(d) },
          h('strong', null, d === today ? 'Today' : DAY_FMT.format(planner.parseDate(d))), ` ${DATE_FMT.format(planner.parseDate(d))}`,
          n > 0 && h('span', { class: 'muted small' }, `  ·  ${n} planned`)));
      })),
      h('div', { class: 'row' }, h('button', { type: 'button', onclick: () => done(null) }, 'Cancel')));
    dlg.addEventListener('close', () => done(null));
    document.body.append(dlg);
    dlg.showModal();
  });
}

let planWeek = null;   // Monday of the week on screen; stays put while you move between pages

// The meal plan: a week at a time, a few recipes or notes on each day.
function viewPlan() {
  setView('plan', 'plan');
  const today = planner.isoDate(new Date());
  if (!planWeek) planWeek = planner.weekStart(today);
  const body = h('div');
  const sub = h('p', { class: 'sub' });
  function paint() {
    const plan = planner.load();
    const dates = planner.weekDates(planWeek);
    const thisWeek = planWeek === planner.weekStart(today);
    sub.textContent = thisWeek ? 'This week' : `Week of ${DATE_FMT.format(planner.parseDate(planWeek))}`;
    const planned = planner.recipesOn(plan, dates).filter(([id]) => lib.byId.get(id));
    fill(body,
      h('div', { class: 'row weeknav' },
        h('button', { type: 'button', 'aria-label': 'Previous week', onclick: () => { planWeek = planner.addDays(planWeek, -7); paint(); } }, '‹ Earlier'),
        h('button', { type: 'button', disabled: thisWeek, onclick: () => { planWeek = planner.weekStart(today); paint(); } }, 'This week'),
        h('button', { type: 'button', 'aria-label': 'Next week', onclick: () => { planWeek = planner.addDays(planWeek, 7); paint(); } }, 'Later ›')),
      dates.map((d) => {
        const label = `${DAY_FMT.format(planner.parseDate(d))} ${DATE_FMT.format(planner.parseDate(d))}`;
        const entries = plan.days[d] || [];
        return h('section', { class: `planday${d === today ? ' today' : ''}${d < today ? ' past' : ''}` },
          h('h2', null, DAY_FMT.format(planner.parseDate(d)), h('span', { class: 'muted' }, ` ${DATE_FMT.format(planner.parseDate(d))}`), d === today && h('span', { class: 'label' }, 'Today')),
          entries.length > 0 && h('ul', { class: 'shoprecipes' }, entries.map((e, n) => {
            const r = e.id ? lib.byId.get(e.id) : null;
            return h('li', null,
              e.note ? h('span', { class: 'plannote' }, e.note)
                : r ? h('a', { href: `#/r/${r.id}` }, r.title)
                  : h('span', { class: 'muted' }, 'A recipe that is no longer in the library'),
              r && h('span', { class: 'muted' }, ` ${timesLabel(Frac.parse(e.f) || new Frac(1n))}`),
              h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Take ${e.note || r?.title || 'this'} off ${label}`, title: 'Take off the plan',
                onclick: () => { planner.removeAt(d, n); paint(); } }, icon('close', { size: 18 })));
          })),
          h('button', { class: 'addday', type: 'button', 'aria-label': `Add to ${label}`, onclick: async () => {
            const entry = await pickForPlan(label);
            if (entry && !planner.add(d, entry)) toast('Could not save the meal plan on this browser');
            paint();
          } }, icon('plus', { size: 18 }), 'Add'));
      }),
      h('section', { class: 'tools stack' },
        h('div', { class: 'row grow' },
          h('button', { class: 'primary', type: 'button', disabled: !planned.length, onclick: () => {
            for (const [id, f] of planned) shop.add(id, f);   // the amount the plan says, so pressing twice doesn't double it
            toast(`${planned.length} ${planned.length === 1 ? 'recipe' : 'recipes'} added to the shopping list`);
            location.hash = '#/shop';
          } }, 'Add this week to the shopping list'),
          h('button', { type: 'button', disabled: !dates.some((d) => plan.days[d]), onclick: async () => {
            if (await confirmDialog('Clear every meal planned for this week?', 'Clear week', true)) { planner.clearDates(dates); paint(); }
          } }, 'Clear week')),
        h('p', { class: 'muted small' }, lib.me
          ? 'Your meal plan and shopping list are saved with your account, so they follow you between your phone and computer.'
          : 'Your meal plan is kept on this device. Sign in (Settings) to have it follow you between your phone and computer.'),
        lib.planSyncError && h('p', { class: 'note' }, `Not saved to your account yet: ${lib.planSyncError}`)));
  }
  fill($app, band('page', h('h1', null, 'Meal plan'), sub), planSeg('plan'), body);
  paint();
  window.scrollTo(0, 0);
}

// The shopping list: every recipe added from its page or from the meal plan, combined into one
// list grouped by aisle, plus anything typed in by hand.
const SKIP_HAVE_KEY = 'recipelib.shop.skiphave';
const skipHave = () => { try { return localStorage.getItem(SKIP_HAVE_KEY) !== '0'; } catch { return true; } };
const setSkipHave = (on) => { try { localStorage.setItem(SKIP_HAVE_KEY, on ? '1' : '0'); } catch { /* private mode */ } };

function viewShop() {
  setView('shop', 'plan');
  const body = h('div');
  const extraIn = h('input', { type: 'text', class: 'full', maxlength: '120', placeholder: 'Add something else: paper towels, coffee…', 'aria-label': 'Add an item' });
  const extraForm = h('form', { class: 'row addextra', onsubmit: (e) => {
    e.preventDefault();
    if (!extraIn.value.trim()) return;
    if (!shop.addExtra(extraIn.value)) toast('Could not save the shopping list on this browser');
    extraIn.value = '';
    paint();
    extraIn.focus();
  } }, extraIn, h('button', { type: 'submit' }, 'Add'));
  // the meal plan from today through the next six days, ready to drop onto the list
  const planAhead = () => {
    const today = planner.isoDate(new Date());
    return planner.recipesOn(planner.load(), planner.weekDates(today)).filter(([id]) => lib.byId.get(id));
  };
  const importPlan = () => {
    const planned = planAhead();
    for (const [id, f] of planned) shop.add(id, f);     // sets the amount to what the plan says, so tapping twice doesn't double it
    toast(`${planned.length} ${planned.length === 1 ? 'recipe' : 'recipes'} from your meal plan`);
    paint();
  };
  const planButton = (cls = '') => {
    const n = planAhead().length;
    return n > 0 && h('button', { class: cls, type: 'button', onclick: importPlan }, `Add my meal plan (${n} ${n === 1 ? 'recipe' : 'recipes'}, next 7 days)`);
  };
  function paint() {
    const list = shop.load();
    let picks = list.items.map((i) => [lib.byId.get(i.id), Frac.parse(i.f) || new Frac(1n)]).filter(([r]) => r && r.kind !== 'link');
    // recipes from the on-demand library need their amounts before they can be added up
    const waiting = picks.filter(([r]) => r.stub && !more.failed.has(r.id));
    if (waiting.length) {
      fill(body, h('p', { class: 'muted', role: 'status' }, 'Getting the recipes…'));
      ensureFull(waiting.map(([r]) => r.id)).then((missing) => { missing.forEach((id) => more.failed.add(id)); if (document.body.dataset.view === 'shop') paint(); });
      return;
    }
    const offline = picks.filter(([r]) => r.stub);
    picks = picks.filter(([r]) => !r.stub);
    if (!picks.length && !list.extras.length && !offline.length) {
      fill(body, h('div', { class: 'empty' },
        h('h2', null, 'Nothing on the list yet'),
        h('p', { class: 'muted' }, 'Open a recipe and choose “Add to shopping list”, or plan your week and add it all at once. The same ingredient from different recipes is added up into one line.'),
        planButton('primary'),
        h('div', { class: 'row', style: 'justify-content:center; margin-top:.8rem' },
          h('a', { class: 'linkbtn', href: '#/plan' }, 'Plan the week'),
          h('a', { class: 'linkbtn', href: '#/' }, 'Browse the recipes'))));
      return;
    }
    const all = [...shop.shoppingList(picks), ...shop.extraLines(list.extras)];
    // things listed under "What can I make?" are already in the kitchen: set them aside, don't buy them
    const kitchen = pantry.load();
    const mine = skipHave() ? pantry.terms(kitchen.have) : [];
    const isHave = (l) => !l.extra && mine.length > 0 && pantry.covers(l.key, mine);
    const lines = all.filter((l) => !isHave(l));
    const have = all.filter(isHave);
    const done = new Set(list.done);
    const left = lines.filter((l) => !done.has(l.key));
    const skipIn = h('input', { type: 'checkbox', checked: skipHave(), onchange: () => { setSkipHave(skipIn.checked); paint(); } });
    const text = () => `Shopping list\n${picks.map(([r, f]) => `${r.title}${f.eq(new Frac(1n)) ? '' : ` (${timesLabel(f)})`}`).join('\n')}\n\n${shop.toTextByAisle(left)}`;
    fill(body,
      picks.length > 0 && h('ul', { class: 'shoprecipes' }, picks.map(([r, f]) => h('li', null,
        h('a', { href: `#/r/${r.id}` }, r.title),
        !f.eq(new Frac(1n)) && h('span', { class: 'muted' }, ` ${timesLabel(f)}`),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Take ${r.title} off the list`, title: 'Take off the list',
          onclick: () => { shop.remove(r.id); paint(); } }, icon('close', { size: 18 }))))),
      offline.length > 0 && h('p', { class: 'note' }, `Not counted yet (needs a connection the first time): ${offline.map(([r]) => r.title).join(', ')}. `,
        h('button', { type: 'button', onclick: () => { more.failed.clear(); paint(); } }, 'Try again')),
      planAhead().some(([id, f]) => !list.items.some((i) => i.id === id && (Frac.parse(i.f) || new Frac(1n)).cmp(f) >= 0)) && planButton(),
      h('p', { class: 'muted small', role: 'status' }, left.length === lines.length
        ? `${lines.length} ${lines.length === 1 ? 'thing' : 'things'} to get`
        : `${left.length} of ${lines.length} still to get`),
      shop.byAisle(lines).map(([aisle, group]) => [
        h('h3', { class: 'aisle' }, aisle),
        h('ul', { class: 'ing shoplist' }, group.map((l) => {
          const btn = h('button', { class: 'tick', type: 'button', 'aria-pressed': String(done.has(l.key)),
            title: l.recipes.join(', '),
            onclick: () => { shop.setDone(l.key, btn.getAttribute('aria-pressed') !== 'true'); buzz(6); paint(); } },
          h('span', { class: 'box' }, icon('check', { size: 16 })),
          h('span', { class: 'what' }, l.name, (l.amounts.length > 0 || l.notes.length > 0) && h('b', null, ` ${[...l.amounts, ...l.notes].join(' + ')}`)));
          return h('li', { class: l.extra ? 'extra' : null }, btn,
            l.extra && h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Remove ${l.name}`, title: 'Remove',
              onclick: () => { shop.removeExtra(l.key); paint(); } }, icon('close', { size: 18 })));
        }))]),
      kitchen.have.length > 0 && h('label', { class: 'check', style: 'margin-top:1.2rem' }, skipIn, 'Leave out what I already have ',
        h('a', { href: '#/pantry' }, '(my kitchen)')),
      have.length > 0 && h('details', { class: 'havebox' },
        h('summary', null, `${have.length} ${have.length === 1 ? 'thing' : 'things'} you already have`),
        h('ul', { class: 'havelist' }, have.map((l) => h('li', null, l.name, (l.amounts.length > 0 || l.notes.length > 0) && h('span', { class: 'muted' }, ` ${[...l.amounts, ...l.notes].join(' + ')}`))))),
      h('section', { class: 'tools stack' },
        h('div', { class: 'row grow' },
          h('button', { type: 'button', onclick: async () => toast(await copyText(text()) ? 'Shopping list copied' : 'Could not copy on this browser') }, 'Copy'),
          navigator.share && h('button', { type: 'button', onclick: () => navigator.share({ title: 'Shopping list', text: text() }).catch(() => {}) }, 'Share'),
          h('button', { type: 'button', onclick: () => window.print() }, 'Print'),
          h('button', { type: 'button', onclick: async () => {
            if (await confirmDialog('Clear the whole shopping list?', 'Clear list', true)) { shop.clear(); paint(); }
          } }, 'Clear list')),
        h('p', { class: 'muted small' }, 'Amounts are added up when they are the same kind of measure (cups with tablespoons, pounds with ounces). ',
          lib.me ? 'The list is saved with your account.' : 'The list is kept on this device; sign in to have it follow you.'),
        lib.planSyncError && h('p', { class: 'note' }, `Not saved to your account yet: ${lib.planSyncError}`)));
  }
  fill($app, pageHead('Shopping list', 'Everything for the recipes you picked, in one list'), planSeg('shop'), extraForm, body);
  paint();
  window.scrollTo(0, 0);
}

// What can I make? Type what is in the kitchen; recipes are ranked by how little is missing.
function viewPantry() {
  setView('pantry', 'list');
  const body = h('div');
  const input = h('input', { type: 'text', class: 'full', maxlength: '200', placeholder: 'chicken, rice, onions…', 'aria-label': 'Ingredients you have', autocapitalize: 'off', autocomplete: 'off' });
  const form = h('form', { class: 'row addextra', onsubmit: (e) => {
    e.preventDefault();
    if (!input.value.trim()) return;
    if (!pantry.add(input.value)) toast('Could not save on this browser');
    input.value = '';
    paint();
    input.focus();
  } }, input, h('button', { type: 'submit' }, 'Add'));
  let shown = PAGE;
  function paint() {
    const p = pantry.load();
    const staplesIn = h('input', { type: 'checkbox', checked: p.staples, onchange: () => { pantry.setStaples(staplesIn.checked); paint(); } });
    const chips = h('div', { class: 'chips have', role: 'group', 'aria-label': 'Ingredients you have' }, p.have.map((name) =>
      h('button', { class: 'chip', type: 'button', 'aria-label': `Remove ${name}`, title: 'Remove', onclick: () => { pantry.remove(name); paint(); } }, name, h('span', { 'aria-hidden': 'true' }, ' ×'))));
    if (!p.have.length) {
      fill(body, h('div', { class: 'empty' },
        h('h2', null, 'What is in your kitchen?'),
        h('p', { class: 'muted' }, 'Add the main things you have, a few at a time or separated by commas. You will see the recipes you can make now, then the ones that need one or two more things.')));
      return;
    }
    const found = pantry.match(lib.all.filter((r) => r.kind !== 'link'), p.have, { assumeStaples: p.staples, limit: 400 });
    const ready = found.filter((m) => !m.missing.length).length;
    fill(body, chips,
      h('label', { class: 'check' }, staplesIn, `I have the basics (${pantry.STAPLES.join(', ')})`),
      h('p', { class: 'count muted small', role: 'status' }, found.length
        ? `${ready ? `${ready.toLocaleString()} you can make now` : 'Nothing you can make with only these'}${found.length > ready ? `, ${(found.length - ready).toLocaleString()} more need one or two things` : ''}`
        : 'No recipes use these yet. Add a few more things.'),
      h('ul', { class: 'rows' }, found.slice(0, shown).map(({ recipe: r, missing }) => h('li', null,
        h('a', { class: 'rc', href: `#/r/${r.id}` }, thumb(r),
          h('span', { class: 'txt' }, h('span', { class: 't' }, r.title),
            h('span', { class: `s ${missing.length ? '' : 'ready'}` }, missing.length ? `Needs ${missing.join(' and ')}` : 'You have everything'))),
        h('div', { class: 'rowacts' },
          h('button', { type: 'button', 'aria-label': `Add ${r.title} to the meal plan`, onclick: async () => {
            const day = await pickDay(r.title);
            if (day && planner.add(day, { id: r.id, f: '1' })) toast(`Planned for ${day === planner.isoDate(new Date()) ? 'today' : DAY_FMT.format(planner.parseDate(day))}`);
          } }, 'Plan it'),
          missing.length > 0 && h('button', { type: 'button', 'aria-label': `Put what ${r.title} needs on the shopping list`, onclick: (e) => {
            if (!shop.has(r.id)) shop.add(r.id, new Frac(1n));
            e.currentTarget.textContent = '✓ On the list';
            toast(`On the shopping list: you only need ${missing.join(' and ')}`);
          } }, shop.has(r.id) ? '✓ On the list' : `Shop for ${missing.length === 1 ? 'it' : 'them'}`))))),
      found.length > shown && h('button', { class: 'more', onclick: () => { shown += PAGE; paint(); } }, 'Show more'),
      h('div', { class: 'row', style: 'margin-top:1rem' },
        h('button', { type: 'button', onclick: async () => {
          if (await confirmDialog('Clear everything you listed?', 'Clear', true)) { pantry.save({ have: [], staples: p.staples }); shown = PAGE; paint(); }
        } }, 'Start over')));
  }
  fill($app, pageHead('What can I make?', 'Recipes from what you have on hand'), form, body);
  paint();
  window.scrollTo(0, 0);
}

/** Choose which collections a recipe is in (and make new ones). */
function collectionsDialog(r, onDone) {
  const listBox = h('ul', { class: 'picklist' });
  const nameIn = h('input', { type: 'text', class: 'full', maxlength: '60', placeholder: 'New collection: Weeknight dinners…', 'aria-label': 'New collection name' });
  let closed = false;
  const close = () => { if (closed) return; closed = true; if (dlg.open) dlg.close(); dlg.remove(); onDone?.(); };
  const dlg = h('dialog', { class: 'pickdialog', 'aria-labelledby': 'col-title' },
    h('h2', { id: 'col-title' }, 'Collections'),
    h('p', { class: 'muted small' }, r.title),
    listBox,
    h('form', { class: 'row', onsubmit: (e) => {
      e.preventDefault();
      const id = collections.create(nameIn.value);
      if (id) { collections.toggle(id, r.id, true); nameIn.value = ''; paint(); }
    } }, nameIn, h('button', { type: 'submit' }, 'Create')),
    h('div', { class: 'row' }, h('button', { class: 'primary', type: 'button', onclick: close }, 'Done')));
  function paint() {
    const all = collections.load();
    fill(listBox, all.length
      ? all.map((c) => {
        const on = c.ids.includes(r.id);
        return h('li', null, h('button', { type: 'button', 'aria-pressed': String(on), onclick: () => { collections.toggle(c.id, r.id, !on); paint(); } },
          h('span', { class: 'e', 'aria-hidden': 'true' }, on ? '✓' : '＋'), c.name, h('span', { class: 'muted small' }, `  ·  ${c.ids.length}`)));
      })
      : h('li', { class: 'muted small' }, 'No collections yet. Name your first one below.'));
  }
  dlg.addEventListener('close', close);
  document.body.append(dlg);
  paint();
  dlg.showModal();
}

// Every ingredient price you have saved (see costui.js).
/** Saves recipes read from a file: to the account when signed in, else on this device. Resolves to how many were saved. */
async function addImported(recs) {
  const online = !!lib.me && cloud.isSignedIn();
  let n = 0;
  try {
    for (const r of recs) {
      const rec = toRecord({ ...r, id: `u-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, source: 'mine' });
      if (online) await cloud.createRecipe(rec); else await saveRecord(rec);
      n++;
    }
  } catch (err) {
    if (n) { if (online) await refreshCloud(); err.message = `${err.message} (${n} added before that)`; }
    throw err;
  }
  if (online) await refreshCloud();
  return n;
}

function viewTransfer() {
  setView('transfer', 'settings');
  fill($app,
    band('page',
      h('div', { class: 'topbar' },
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => goBack('#/settings') }, icon('back')),
        h('span', { class: 'sp' })),
      h('h1', null, 'Import and export'),
      h('p', { class: 'sub' }, 'Paprika, Mealie, Tandoor, Cooklang and more')),
    transferPage({
      h, fill, toast, add: addImported, signedIn: !!lib.me && cloud.isSignedIn(),
      mine: () => lib.all.filter((r) => SOURCE_GROUP[r.source] === 'mine'),
      starred: () => lib.all.filter((r) => isStarred(r.id)),
    }));
  window.scrollTo(0, 0);
}

function viewPrices() {
  setView('prices', 'settings');
  fill($app,
    band('page',
      h('div', { class: 'topbar' },
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => goBack('#/settings') }, icon('back')),
        h('span', { class: 'sp' })),
      h('h1', null, 'Ingredient prices'),
      h('p', { class: 'sub' }, 'For food cost on every recipe')),
    priceBook({ h, fill, toast }));
  window.scrollTo(0, 0);
}

// What you have cooked, most recent first.
function viewCooked() {
  setView('cooked', 'starred');
  const log = cooklog.load();
  const today = planner.isoDate(new Date());
  const rows = cooklog.recent(log).map(([id, e]) => [lib.byId.get(id), e]).filter(([r]) => r);
  fill($app,
    band('page', h('h1', null, 'Cooked'), h('p', { class: 'sub' }, `${rows.length} ${rows.length === 1 ? 'recipe' : 'recipes'} you have made`)),
    h('p', null, h('a', { class: 'linkbtn', href: '#/starred' }, '‹ Starred and collections')),
    rows.length
      ? h('ul', { class: 'rows' }, rows.map(([r, e]) => {
        const { times, last } = cooklog.summary(e);
        return h('li', null, h('a', { class: 'rc', href: `#/r/${r.id}` }, thumb(r), h('span', { class: 'txt' }, h('span', { class: 't' }, r.title),
          h('span', { class: 's' }, `${e.rating ? `${'★'.repeat(e.rating)} · ` : ''}${times === 1 ? 'Made once' : `Made ${times} times`}, last ${last === today ? 'today' : DATE_FMT.format(planner.parseDate(last))}`))));
      }))
      : h('div', { class: 'empty' }, h('h2', null, 'Nothing cooked yet'),
        h('p', { class: 'muted' }, 'Open a recipe and tap “I made this” to start your cook log.'),
        h('a', { class: 'linkbtn', href: '#/' }, 'Browse the recipes')));
  window.scrollTo(0, 0);
}

// One collection: its recipes, with rename and delete.
function viewCollection(id) {
  const c = collections.get(id);
  if (!c) return viewMissing();
  setView('collection', 'starred');
  const recipes = c.ids.map((rid) => lib.byId.get(rid)).filter(Boolean);
  fill($app,
    band('page', h('h1', null, c.name), h('p', { class: 'sub' }, `${recipes.length} ${recipes.length === 1 ? 'recipe' : 'recipes'}`)),
    h('p', null, h('a', { class: 'linkbtn', href: '#/starred' }, '‹ Starred and collections')),
    recipes.length
      ? h('ul', { class: 'rows' }, recipes.map((r) => h('li', null,
        h('a', { class: 'rc', href: `#/r/${r.id}` }, thumb(r), h('span', { class: 'txt' }, h('span', { class: 't' }, r.title), h('span', { class: 's' }, r.source === 'base' ? r.categories.slice(0, 2).join(' · ') : badgeText(r)))),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Take ${r.title} out of ${c.name}`, title: 'Take out of this collection',
          onclick: () => { collections.toggle(c.id, r.id, false); viewCollection(id); } }, icon('close', { size: 18 })))))
      : h('div', { class: 'empty' }, h('h2', null, 'Nothing in here yet'),
        h('p', { class: 'muted' }, 'Open a recipe and choose “Collections” to add it.'),
        h('a', { class: 'linkbtn', href: '#/' }, 'Browse the recipes')),
    h('section', { class: 'tools stack' }, h('div', { class: 'row grow' },
      h('button', { type: 'button', onclick: () => {
        const dlgName = h('input', { type: 'text', class: 'full', maxlength: '60', value: c.name, 'aria-label': 'Collection name' });
        const dlg = h('dialog', null, h('form', { onsubmit: (e) => { e.preventDefault(); if (collections.rename(c.id, dlgName.value)) { dlg.close(); dlg.remove(); viewCollection(id); } } },
          h('h2', { style: 'margin-top:0' }, 'Rename collection'), dlgName,
          h('div', { class: 'row' }, h('button', { type: 'button', onclick: () => { dlg.close(); dlg.remove(); } }, 'Cancel'), h('button', { class: 'primary', type: 'submit' }, 'Save'))));
        document.body.append(dlg); dlg.showModal(); dlgName.select();
      } }, 'Rename'),
      h('button', { type: 'button', onclick: async () => {
        if (await confirmDialog(`Delete the collection “${c.name}”? The recipes themselves stay in the library.`, 'Delete collection', true)) { collections.remove(c.id); location.hash = '#/starred'; }
      } }, 'Delete collection'))));
  window.scrollTo(0, 0);
}

function viewLinks(collectionId) {
  const c = COLLECTIONS.find((x) => x.id === collectionId);
  if (!c) return viewMissing();
  setView('list', 'list');
  const input = h('input', { type: 'search', placeholder: `Search ${c.site} recipes`, autocomplete: 'off', 'aria-label': `Search ${c.site} recipes` });
  const box = h('div');
  const paint = () => {
    const q = input.value.trim().toLowerCase();
    fill(box, c.sections.map(([name, rows]) => {
      const hits = rows.filter(([t]) => !q || t.toLowerCase().includes(q));
      return hits.length > 0 && [h('h2', null, name), h('ul', { class: 'rows' }, hits.map(([t, url]) => h('li', null,
        h('a', { class: 'rc', href: url, target: '_blank', rel: 'noopener' },
          h('span', { class: 'tile', 'aria-hidden': 'true', 'data-sec': 2 }, '🌱'),
          h('span', { class: 'txt' }, h('span', { class: 't' }, t), h('span', { class: 'c' }, `${c.site} · opens her website ↗`))))))];
    }));
  };
  input.addEventListener('input', paint);
  fill($app,
    band('page',
      h('div', { class: 'topbar' },
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => goBack('#/') }, icon('back')),
        h('span', { class: 'sp' })),
      h('h1', null, `Vegan recipes from ${c.site}`),
      h('p', { class: 'sub' }, c.blurb)),
    h('div', { class: 'card stack' },
      h('p', { class: 'small' }, `These recipes belong to ${c.author}. Each one opens on ${c.site}, so she gets the visit and the credit. To keep one you cook often, open it, copy the address, then tap Import below. It is saved in your own recipes with her name and a link back.`),
      h('div', { class: 'row grow' },
        h('a', { class: 'linkbtn', href: '#/import' }, '⤓ Import one from a link'),
        h('a', { class: 'linkbtn', href: c.home, target: '_blank', rel: 'noopener' }, `Browse all of ${c.site} ↗`))),
    h('div', { class: 'searchbar' }, h('label', { class: 'search' }, icon('search', { size: 22 }), input)),
    box);
  paint();
  window.scrollTo(0, 0);
}

/** Paste one recipe link; the recipe is read, checked in the editor, then saved with credit. */
function viewImport() {
  setView('edit', 'new');
  const signedIn = !!lib.me && cloud.isSignedIn();
  const url = h('input', { class: 'full', type: 'url', placeholder: 'https://www.noracooks.com/…', autocomplete: 'off', autocapitalize: 'off', 'aria-label': 'Recipe page address' });
  const status = h('p', { class: 'muted small', role: 'status' });
  const go = h('button', { class: 'primary', type: 'button', disabled: !signedIn, onclick: run }, 'Get recipe');
  async function run() {
    let link = url.value.trim();
    if (!link) { url.focus(); return; }
    if (!/^https?:\/\//i.test(link)) link = `https://${link}`;
    go.disabled = true;
    status.textContent = 'Reading the page…';
    try {
      const res = await cloud.fetchRecipePage(link);
      if (!res || !res.recipe) throw new Error((res && res.error) || 'No recipe was found on that page.');
      const r = recipeFromSchema(res.recipe, res.url || link, res.site || '');
      r.imported = true;
      const dup = lib.all.find((x) => x.src?.url && x.src.url === r.src.url);
      if (dup) { toast('That recipe is already in your recipes'); location.hash = `#/r/${encodeURIComponent(dup.id)}`; return; }
      viewEdit(null, r);
    } catch (err) {
      status.textContent = err.message;
      go.disabled = false;
    }
  }
  url.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
  fill($app,
    band('page',
      h('div', { class: 'topbar' },
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => goBack('#/new') }, icon('back')),
        h('span', { class: 'sp' })),
      h('h1', null, 'Import from a web page')),
    h('p', { class: 'muted' }, 'Paste the address of one recipe page. You check it before it is saved. It goes into your own private recipes with the author’s name and a link back to the original. Only the ingredients, method and yield are taken. Photos and stories stay on their site.'),
    !signedIn && h('p', { class: 'note' }, 'Sign in first (Settings). The phone can’t read other websites on its own, so the page is read through your account.'),
    h('label', { class: 'field' }, h('span', null, 'Recipe page address'), url),
    h('div', { class: 'row grow' }, go),
    status,
    COLLECTIONS.map((c) => h('p', { class: 'small' }, h('a', { href: `#/links/${c.id}` }, `Browse vegan recipes from ${c.site}`))));
  window.scrollTo(0, 0);
  if (signedIn) url.focus();
}

function viewMissing() {
  if (lib.moreState === 'loading') {     // it may be one of the recipes still on its way
    setView('loading', 'list');
    fill($app, pageHead('One moment'), h('div', { class: 'sk' }), h('div', { class: 'sk' }));
    return;
  }
  setView('list', 'list');
  fill($app, pageHead('Recipe not found'), h('p', null, h('a', { href: '#/' }, 'Back to the library')));
}

// ----------------------------------------------------------------- settings

let installPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installPrompt = e; });

async function viewSettings() {
  setView('settings', 'settings');
  const mine = [...lib.mine.values()];
  const counts = {
    new: mine.filter((m) => !m.deleted && !lib.base.some((b) => b.id === m.id)).length,
    edited: mine.filter((m) => !m.deleted && lib.base.some((b) => b.id === m.id)).length,
    removed: mine.filter((m) => m.deleted).length,
  };
  const swReady = isNativeApp() || ('serviceWorker' in navigator && !!navigator.serviceWorker.controller);
  const persisted = (await navigator.storage?.persisted?.().catch(() => false)) || false;
  const stat = (k, v) => h('div', { class: 'stat' }, h('span', null, k), h('strong', null, v));
  const appVersion = await (async () => {
    try { const k = (await caches.keys()).find((x) => x.startsWith('sprig-')); return k ? k.slice(6) : 'not cached yet'; } catch { return 'unknown'; }
  })();

  const fileIn = h('input', { type: 'file', accept: 'application/json,.json', hidden: true, onchange: importBackup });

  async function importBackup() {
    const file = fileIn.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      if (data.app !== 'recipelib' || !Array.isArray(data.records)) throw new Error('not a backup');
      const recs = data.records.filter((x) => x && typeof x.id === 'string');
      addStars(Array.isArray(data.stars) ? data.stars : []);
      await store.putMany(recs);
      for (const x of recs) lib.mine.set(x.id, x);
      rebuild();
      toast(`Imported ${recs.length} recipe change${recs.length === 1 ? '' : 's'}`);
      viewSettings();
    } catch { toast('That file is not a Sprig backup'); }
  }

  const localNew = mine.filter((m) => !m.deleted && !lib.base.some((b) => b.id === m.id));
  async function moveToAccount() {
    if (!await confirmDialog(`Move ${localNew.length} recipe${localNew.length === 1 ? '' : 's'} from this device into your account? They will then be saved online and available on every device you sign in on.`, 'Move')) return;
    let moved = 0; let problem = null;
    for (const rec of localNew) {
      try {
        const row = await cloud.createRecipe(rec);
        if (isStarred(rec.id)) addStars([row.id]);
        await store.remove(rec.id); lib.mine.delete(rec.id); moved++;
      } catch (err) { problem = err; break; }
    }
    await refreshCloud();
    toast(problem ? `Moved ${moved}. Stopped: ${problem.message}` : `Moved ${moved} recipe${moved === 1 ? '' : 's'} to your account`, problem ? 6000 : 3000);
    viewSettings();
  }

  function exportBackup() {
    const blob = new Blob([JSON.stringify({ app: 'recipelib', v: 1, records: [...lib.mine.values()], stars: starIds() }, null, 1)], { type: 'application/json' });
    const a = h('a', { href: URL.createObjectURL(blob), download: `sprig-backup-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  async function restoreRemoved() {
    const ids = mine.filter((m) => m.deleted).map((m) => m.id);
    await store.removeMany(ids);
    ids.forEach((id) => lib.mine.delete(id));
    rebuild();
    toast(`Restored ${ids.length} recipe${ids.length === 1 ? '' : 's'}`);
    viewSettings();
  }

  fill($app, 
    pageHead('Settings & backup'),
    accountCard(ctx),
    h('h2', null, 'This device'),
    h('section', { class: 'card stack' },
      h('strong', null, 'Status'),
      stat('Recipes in library', lib.all.length.toLocaleString()),
      stat('Works offline', swReady ? 'Yes' : 'Not yet (open once while online)'),
      stat('App version', appVersion),
      stat('Your changes are saved on this device', store.persistent ? 'Yes' : 'No (private browsing?)'),
      stat('Protected from automatic cleanup', persisted ? 'Yes' : 'No'),
      !persisted && navigator.storage?.persist && h('button', { onclick: async () => { toast((await navigator.storage.persist()) ? 'Done' : 'The browser declined'); viewSettings(); } }, 'Ask the browser to keep my data'),
      installPrompt && h('button', { class: 'primary', onclick: async () => { installPrompt.prompt(); installPrompt = null; viewSettings(); } }, 'Install app on this device')),
    h('h2', null, 'Food cost'),
    h('section', { class: 'card stack' },
      stat('Ingredient prices saved', String(Object.keys(prices.load().items).length)),
      h('p', { class: 'muted small' }, 'Prices you enter on a recipe are remembered for every recipe that uses the food. Review them, or import a supplier list, here.'),
      h('a', { class: 'linkbtn', href: '#/prices' }, 'Open the price book')),
    h('h2', null, 'Your recipes'),
    lib.me && localNew.length > 0 && h('section', { class: 'card stack' },
      h('strong', null, `${localNew.length} recipe${localNew.length === 1 ? ' is' : 's are'} only on this device`),
      h('p', { class: 'muted small' }, 'Move them into your account so they are backed up online and open on your other devices.'),
      h('button', { class: 'primary', onclick: moveToAccount }, 'Move them to my account')),
    h('section', { class: 'card stack' },
      stat('Added by you', counts.new), stat('Edited built-in recipes', counts.edited), stat('Removed built-in recipes', counts.removed),
      h('p', { class: 'muted small' }, 'Your additions and edits are stored only on this device. Export a backup to move them to another phone or keep a safe copy.'),
      h('div', { class: 'row grow' },
        h('button', { class: 'primary', onclick: exportBackup }, 'Export backup'),
        h('button', { onclick: () => fileIn.click() }, 'Import backup'),
        counts.removed > 0 && h('button', { onclick: restoreRemoved }, 'Restore removed')),
      h('p', null, h('a', { class: 'linkbtn', href: '#/transfer' }, 'Import and export recipes (Paprika, Mealie, Tandoor, PDF book)')),
      fileIn),
    h('h2', null, 'Install on your phone'),
    h('section', { class: 'card' },
      h('p', null, h('strong', null, 'iPhone / iPad: '), 'open this page in Safari, tap the Share button, then “Add to Home Screen”.'),
      h('p', null, h('strong', null, 'Android: '), 'open it in Chrome, tap the ⋮ menu, then “Install app” (or “Add to Home screen”).'),
      h('p', { class: 'muted small' }, 'Open it once with a connection first so the recipes download. After that it works with no signal. Installing it to the home screen also stops iPhones from clearing its data after a few weeks of not using it.')));
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------- router

// Back button: browsers differ on history.length (Firefox counts the new-tab page), so the app
// numbers its own history entries and only calls history.back() when an earlier app page exists.
let appIndex = 0;
let stamped = false;
function stampHistory() {
  const st = history.state;
  if (st && typeof st.i === 'number') appIndex = st.i;
  else {
    appIndex = stamped ? appIndex + 1 : 0;
    try { history.replaceState({ i: appIndex }, ''); } catch { /* ignore */ }
  }
  stamped = true;
}
function goBack(fallback = '#/') {
  if (appIndex > 0) history.back(); else location.hash = fallback;
}


function route() {
  stampHistory();
  clearView();
  $app.removeAttribute('aria-busy');
  $app.classList.remove('enter'); void $app.offsetWidth; $app.classList.add('enter');
  const hash = location.hash.replace(/^#\/?/, '');
  const [kind, arg] = hash.split('/');
  const id = arg ? decodeURIComponent(arg) : null;
  if (kind === 'r' && id) return viewRecipe(id);
  if (kind === 's' && id) return viewShared(id);
  if (kind === 'edit' && id) return viewEdit(id);
  if (kind === 'new') return viewEdit(null);
  if (kind === 'settings') return viewSettings();
  if (kind === 'links') return viewLinks(id || COLLECTIONS[0].id);
  if (kind === 'import') return viewImport();
  if (kind === 'admin') return viewAdmin(ctx);
  if (kind === 'join') return viewJoin(ctx, id);
  if (kind === 'starred') return viewList(true);
  if (kind === 'shop') return viewShop();
  if (kind === 'plan') return viewPlan();
  if (kind === 'pantry') return viewPantry();
  if (kind === 'c' && id) return viewCollection(id);
  if (kind === 'cooked') return viewCooked();
  if (kind === 'prices') return viewPrices();
  if (kind === 'transfer') return viewTransfer();
  return viewList();
}

const ctx = {
  h, fill, toast, icon, lib, $app, setView, goBack, refreshCloud, clearCloud, confirmDialog, infoDialog, pageHead,
  rerender: () => route(), joinCode: '',
};

async function boot() {
  const linkType = cloud.takeSessionFromHash();      // arriving from a confirmation / reset email
  if (linkType) history.replaceState(history.state, '', `${location.pathname}${location.search}#/settings`);
  loadCloudCache();
  restoreTimers();
  document.addEventListener('timerdone', (e) => toast(`${e.detail.label} timer is done`, 6000));
  try {
    const [res, mine] = await Promise.all([fetch('data/recipes.json'), store.all()]);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    lib.base = data.recipes.map(fromRow);
    for (const rec of mine) lib.mine.set(rec.id, rec);
    rebuild();
  } catch (err) {
    fill($app, h('div', { class: 'pad' }, h('h1', null, 'Could not load the recipes'),
      h('p', null, 'Connect to the internet and reload once, then it will work offline.'), h('p', { class: 'muted small' }, String(err))));
    return;
  }
  window.addEventListener('hashchange', route);
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('dialog[open]')) return;
    const view = document.body.dataset.view;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    if (e.key === 'Escape' && (view === 'recipe' || view === 'edit')) { goBack('#/'); }
    else if (e.key === '/' && view === 'list' && !typing) { const s = document.querySelector('input[type=search]'); if (s) { e.preventDefault(); s.focus(); } }
  });
  route();
  registerWorker();
  loadMore();
  if (linkType === 'recovery') ctx.recovery = true;
  if (linkType === 'invite') ctx.recovery = 'invite';      // signed in by the invite email: choose a password
  if (linkType?.startsWith('error:')) {
    infoDialog('That link didn’t work', `${linkType.slice(6)} Ask for a new invite, or use “Forgot password?” to get a new sign-in link.`);
  } else if (linkType) {
    const [t, m] = {
      recovery: ['Choose a new password', 'You’re signed in. Choose a new password below.'],
      invite: ['Welcome to Sprig!', 'Your invite worked and you’re signed in. Choose a password below so you can sign in on other devices.'],
    }[linkType] || ['Email confirmed', 'Your account is ready and you’re signed in.'];
    infoDialog(t, m);
  }
  if (cloud.isSignedIn()) {
    const hadAccount = !!lib.me;
    await refreshCloud();
    const view = document.body.dataset.view;
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || '') && document.activeElement.value;
    if ((['plan', 'shop', 'pantry', 'collection'].includes(view) && !typing && !document.querySelector('dialog[open]')) || view === 'list' || (view === 'recipe' && !hadAccount) || (view === 'settings' && !ctx.recovery && !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || '') && location.hash.indexOf('admin') < 0)) route();
  }
}

function showUpdate() {
  if (document.querySelector('.updatebar')) return;
  document.body.append(h('div', { class: 'updatebar', role: 'status' },
    h('span', null, 'A new version is ready.'),
    h('button', { type: 'button', onclick: () => location.reload() }, 'Update now'),
    h('button', { type: 'button', class: 'later', 'aria-label': 'Dismiss', onclick: (e) => e.target.closest('.updatebar').remove() }, '×')));
}

/** True inside the iOS / Android app (Capacitor), where the files ship with the app itself. */
const isNativeApp = () => !!window.Capacitor?.isNativePlatform?.();

function registerWorker() {
  // the native apps carry every file already; a service worker there would only serve stale copies after an update
  if (isNativeApp() || !('serviceWorker' in navigator)) return;
  let controlled = !!navigator.serviceWorker.controller;      // false only on the very first visit
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (controlled) showUpdate(); else { controlled = true; toast('Ready to use offline', 5000); }
  });
  navigator.serviceWorker.register('sw.js').then((reg) => {
    // look for a newer version now, whenever the app comes back to the front, and hourly
    const check = () => reg.update().catch(() => {});
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') check(); });
    setInterval(check, 60 * 60 * 1000);
  }).catch((err) => console.warn('Service worker failed:', err));
}

boot();
