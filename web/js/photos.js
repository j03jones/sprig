// Photos: shrink on the phone before upload, download with the person's login, and keep a copy
// on the device so photos still show with no signal. Photo files never change once uploaded
// (a new photo gets a new random name), so a cached copy is always correct.
import * as cloud from './cloud.js';

const CACHE = 'photos-v1';            // not "sprig-…": the service worker clears those on each update
const urls = new Map();               // path -> object URL for this session
const pending = new Map();            // path -> promise, so the same photo is not fetched twice at once

const cacheKey = (path) => `/__photos/${path}`;

/** An object URL for a stored photo, from the device cache or the server. Null if unavailable. */
export function photoURL(path) {
  if (!path) return Promise.resolve(null);
  if (urls.has(path)) return Promise.resolve(urls.get(path));
  if (pending.has(path)) return pending.get(path);
  const p = (async () => {
    let blob = null;
    try {
      const c = await caches.open(CACHE);
      const hit = await c.match(cacheKey(path));
      if (hit) blob = await hit.blob();
    } catch { /* no Cache Storage (private mode): just download */ }
    if (!blob) {
      try { blob = await cloud.downloadPhoto(path); } catch { return null; }
      try { (await caches.open(CACHE)).put(cacheKey(path), new Response(blob, { headers: { 'Content-Type': blob.type } })); } catch { /* fine */ }
    }
    const url = URL.createObjectURL(blob);
    urls.set(path, url);
    return url;
  })().finally(() => pending.delete(path));
  pending.set(path, p);
  return p;
}

/** Put a just-uploaded photo straight into the cache so it shows without downloading it again. */
async function remember(path, blob) {
  urls.set(path, URL.createObjectURL(blob));
  try { (await caches.open(CACHE)).put(cacheKey(path), new Response(blob, { headers: { 'Content-Type': blob.type } })); } catch { /* fine */ }
}

/** Shrink a camera photo to at most `max` pixels on its long side, as a JPEG (about 150-300 KB). */
export async function shrink(file, max = 1200, quality = 0.82) {
  let src;
  try { src = await createImageBitmap(file, { imageOrientation: 'from-image' }); } catch {
    src = await new Promise((resolve, reject) => {           // older Safari
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('That file is not a photo this browser can open.'));
      img.src = URL.createObjectURL(file);
    });
  }
  const w = src.width; const hgt = src.height;
  const scale = Math.min(1, max / Math.max(w, hgt));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(w * scale); canvas.height = Math.round(hgt * scale);
  const g = canvas.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, canvas.width, canvas.height);   // transparent PNGs get a white background
  g.drawImage(src, 0, 0, canvas.width, canvas.height);
  if (src.close) src.close();
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not prepare the photo.'))), 'image/jpeg', quality));
}

const randomName = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}.jpg`;

/** Shrink and upload a photo into one of the person's folders ('recipes', 'library', 'avatars'). Returns its path. */
export async function upload(folder, file, max = 1200) {
  if (!navigator.onLine) throw new cloud.CloudError('Photos need an internet connection. Try again when you have signal.', 0);
  const blob = await shrink(file, max);
  const path = `${folder}/${cloud.currentUser().id}/${randomName()}`;
  await cloud.uploadPhoto(path, blob);
  await remember(path, blob);
  return path;
}

/** Delete photo files, ignoring failures (a leftover file only costs a little storage). */
export async function discard(paths) {
  const list = paths.filter(Boolean);
  if (!list.length) return;
  try { await cloud.removePhotos(list); } catch { /* best effort */ }
  try { const c = await caches.open(CACHE); await Promise.all(list.map((p) => c.delete(cacheKey(p)))); } catch { /* fine */ }
  for (const p of list) { const u = urls.get(p); if (u) URL.revokeObjectURL(u); urls.delete(p); }
}

/** An <img> that fills in once the photo is ready (or removes itself if it cannot be loaded). */
export function photoImg(path, attrs = {}) {
  const img = document.createElement('img');
  for (const [k, v] of Object.entries(attrs)) img.setAttribute(k, v);
  img.decoding = 'async';
  photoURL(path).then((u) => { if (u) img.src = u; else img.remove(); });
  return img;
}

/** Ask for a photo: on phones this offers the camera or the photo library. Resolves to a File or null. */
export function pickPhoto() {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'image/*';
    input.addEventListener('change', () => resolve(input.files[0] || null), { once: true });
    input.addEventListener('cancel', () => resolve(null), { once: true });
    input.click();
  });
}
