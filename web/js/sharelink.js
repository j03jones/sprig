// Share a recipe as a link. The link carries the recipe itself (compressed, after the # so it never
// reaches a server), so it opens for anyone with the app, no account needed. It is a copy: later edits
// do not change a link that was already sent.
//
//   #/s/<payload>      payload = version digit + base64url
//                      '1' = deflate-raw compressed JSON, '0' = plain JSON (browsers without CompressionStream)

const LIMITS = { json: 60000, title: 300, ings: 300, field: 600, dir: 20000, cats: 20 };

const b64 = {
  enc(bytes) {
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  },
  dec(text) {
    const s = atob(text.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((text.length + 3) % 4));
    return Uint8Array.from(s, (c) => c.charCodeAt(0));
  },
};

async function pipe(bytes, stream, cap) {
  const out = new Response(new Blob([bytes]).stream().pipeThrough(stream)).body.getReader();
  const parts = [];
  let size = 0;
  for (;;) {
    const { value, done } = await out.read();
    if (done) break;
    size += value.length;
    if (cap && size > cap) { out.cancel().catch(() => {}); throw new Error('too big'); }   // a tiny link must not unpack to something huge
    parts.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const p of parts) { all.set(p, at); at += p.length; }
  return all;
}

/** The parts of a recipe record that travel in a link (no id, photo or private notes). */
export function slim(rec, from = '') {
  return {
    t: rec.title, c: rec.categories || [], q: rec.yq || '', u: rec.yu || '', r: rec.yr || '', d: rec.dir || '',
    i: rec.ings || [],
    ...(rec.adapted ? { a: [rec.adapted.author || '', rec.adapted.name || '', rec.adapted.url || ''] } : {}),
    ...(from ? { f: String(from).slice(0, 60) } : {}),
  };
}

export async function packRecipe(rec, from = '') {
  const bytes = new TextEncoder().encode(JSON.stringify(slim(rec, from)));
  if (typeof CompressionStream === 'function') return `1${b64.enc(await pipe(bytes, new CompressionStream('deflate-raw')))}`;
  return `0${b64.enc(bytes)}`;
}

const str = (v, max) => (typeof v === 'string' ? v.slice(0, max) : '');

/** Reads a link's payload back into a recipe record, or throws. Everything is checked: a link can be hand-made. */
export async function unpackRecipe(payload) {
  if (typeof payload !== 'string' || payload.length < 2 || payload.length > 90000) throw new Error('bad link');
  const raw = b64.dec(payload.slice(1));
  let bytes;
  if (payload[0] === '1') {
    if (typeof DecompressionStream !== 'function') throw new Error('This browser cannot open shared recipe links. Update it and try again.');
    bytes = await pipe(raw, new DecompressionStream('deflate-raw'), LIMITS.json);
  } else if (payload[0] === '0') bytes = raw;
  else throw new Error('bad link');
  if (bytes.length > LIMITS.json) throw new Error('bad link');
  const o = JSON.parse(new TextDecoder().decode(bytes));
  if (!o || typeof o !== 'object' || !str(o.t, 1) || !Array.isArray(o.i)) throw new Error('bad link');
  const adapted = Array.isArray(o.a) ? { author: str(o.a[0], 120), name: str(o.a[1], 120), url: /^https?:\/\//i.test(o.a[2] || '') ? str(o.a[2], 500) : '' } : null;
  return {
    from: str(o.f, 60),
    rec: {
      id: 'shared-link',
      title: str(o.t, LIMITS.title),
      categories: (Array.isArray(o.c) ? o.c : []).slice(0, LIMITS.cats).map((c) => str(c, 80)).filter(Boolean),
      tags: [],
      yq: str(o.q, 20), yu: str(o.u, 40), yr: str(o.r, LIMITS.field), dir: str(o.d, LIMITS.dir),
      ings: o.i.slice(0, LIMITS.ings).map((x) => (Array.isArray(x) ? [str(x[0], 20), str(x[1], LIMITS.field), str(x[2], 40), str(x[3], LIMITS.field), str(x[4], 120)] : ['', '', '', '', ''])),
      ...(adapted && (adapted.author || adapted.name || adapted.url) ? { adapted } : {}),
    },
  };
}

/** The full address to send. */
export const linkFor = (payload) => `${location.origin}${location.pathname}#/s/${payload}`;
