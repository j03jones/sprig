// Service worker: caches the whole app (including the recipe data) so it works with no signal.
// VERSION is stamped with the commit id by the GitHub Pages workflow; bump it by hand if you
// deploy some other way, otherwise phones keep the old cached copy.
const VERSION = 'dev';
const CACHE = `sprig-${VERSION}`;
const ASSETS = [
  './', 'index.html', 'style.css', 'manifest.webmanifest',
  'js/app.js', 'js/units.js', 'js/unitdata.js', 'js/groups.js', 'js/linkdata.js', 'js/webimport.js', 'js/qr.js', 'js/model.js', 'js/store.js', 'js/ui.js', 'js/timers.js', 'js/config.js', 'js/cloud.js', 'js/account.js', 'js/photos.js', 'js/sharelink.js', 'js/nutrition.js', 'js/nutridata.js', 'js/prices.js', 'js/costui.js', 'js/transfer.js', 'js/transferui.js', 'js/shopping.js', 'js/aisledata.js', 'js/planner.js', 'js/pantry.js', 'js/collections.js', 'js/cooklog.js',
  'data/recipes.json',
  'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png',
  'icons/icon-maskable-512.png', 'icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  // 'reload' skips the browser's own HTTP cache so a new version never installs from stale copies
  event.waitUntil(caches.open(CACHE)
    .then((c) => Promise.all(ASSETS.map((a) => c.add(new Request(a, { cache: 'reload' })))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('sprig-') && k !== CACHE && k !== 'sprig-fonts' && k !== 'sprig-more').map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method === 'GET' && (url.host === 'fonts.googleapis.com' || url.host === 'fonts.gstatic.com')) {
    // web fonts: serve the saved copy right away and refresh it quietly; kept across app versions
    event.respondWith((async () => {
      const cache = await caches.open('sprig-fonts');
      const saved = await cache.match(req);
      const fresh = fetch(req).then((res) => { if (res.ok || res.type === 'opaque') cache.put(req, res.clone()); return res; }).catch(() => null);
      return saved || (await fresh) || Response.error();
    })());
    return;
  }
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.endsWith('/data/more.json') || url.pathname.includes('/data/more/')) {
    // the on-demand part of the library, kept across app versions. more.json says which set is
    // current, so the network is asked first; the files of a set never change, so a saved copy wins.
    event.respondWith((async () => {
      const cache = await caches.open('sprig-more');
      const fresh = (init) => fetch(req, init).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; });
      if (url.pathname.endsWith('/data/more.json')) {
        // 'no-cache' makes the browser check with the server, so a republished library shows up at once
        try { return await fresh({ cache: 'no-cache' }); } catch (err) { return (await cache.match(req)) || Response.error(); }
      }
      return (await cache.match(req)) || fresh();
    })());
    return;
  }
  event.respondWith((async () => {
    const cached = await caches.match(req, { ignoreSearch: true });
    if (cached) return cached;
    try {
      const res = await fetch(req);
      if (res.ok) (await caches.open(CACHE)).put(req, res.clone());
      return res;
    } catch (err) {
      if (req.mode === 'navigate') return (await caches.match('index.html')) || Response.error();
      throw err;
    }
  })());
});
