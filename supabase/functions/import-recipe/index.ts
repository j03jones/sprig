// import-recipe: reads ONE recipe page a signed-in person chose and returns only its schema.org Recipe
// block (title, ingredients, method, yield, author...). The phone app turns that into a private recipe
// with credit and a link back (web/js/webimport.js). Browsers can't read other sites directly, which is
// why this runs on the server. Nothing is stored here.
//
// Deploy:  supabase functions deploy import-recipe      (JWT verification stays ON: signed-in users only)
const MAX_BYTES = 5 * 1024 * 1024;
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });

function allowedUrl(raw: string): URL | null {
  let u: URL;
  try { u = new URL(raw); } catch { return null; }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
  const host = u.hostname.toLowerCase();
  // public websites only: no IP literals, local names or internal hosts
  if (!host.includes('.') || host.endsWith('.local') || host.endsWith('.internal') || host === 'localhost') return null;
  if (/^[\d.]+$/.test(host) || host.includes(':') || host.startsWith('[')) return null;
  if (u.port && u.port !== '80' && u.port !== '443') return null;
  return u;
}

function* walk(node: unknown): Generator<Record<string, unknown>> {
  if (Array.isArray(node)) { for (const n of node) yield* walk(n); return; }
  if (node && typeof node === 'object') {
    const o = node as Record<string, unknown>;
    yield o;
    for (const k of ['@graph', 'mainEntity', 'itemListElement']) if (k in o) yield* walk(o[k]);
  }
}
const isRecipe = (o: Record<string, unknown>) => ([] as unknown[]).concat(o['@type'] ?? []).map(String).includes('Recipe');

function findRecipe(html: string) {
  const re = /<script[^>]*type\s*=\s*["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  for (const m of html.matchAll(re)) {
    let data: unknown;
    try { data = JSON.parse(m[1].trim()); } catch { continue; }
    for (const o of walk(data)) if (isRecipe(o)) return o;
  }
  return null;
}

// Keep only the fields the app uses; drop images, video, reviews, descriptions and the rest.
const KEEP = ['@type', 'name', 'author', 'publisher', 'url', 'recipeYield', 'recipeIngredient', 'ingredients',
  'recipeInstructions', 'recipeCategory', 'recipeCuisine', 'suitableForDiet'];
const pick = (o: Record<string, unknown>) => Object.fromEntries(KEEP.filter((k) => k in o).map((k) => [k, o[k]]));

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'Use POST.' }, 405);
  let url: URL | null = null;
  try { url = allowedUrl(String((await req.json()).url || '').trim()); } catch { /* bad body */ }
  if (!url) return json({ error: 'Please enter the address of a public recipe page (https://...).' }, 400);

  let res: Response;
  try {
    res = await fetch(url, {
      redirect: 'follow', signal: AbortSignal.timeout(15000),
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; Sprig; personal recipe box)', Accept: 'text/html,*/*;q=0.5' },
    });
  } catch {
    return json({ error: 'Could not reach that website. Check the link.' }, 502);
  }
  const finalUrl = allowedUrl(res.url || url.href);
  if (!finalUrl) return json({ error: 'That link redirects somewhere that can’t be read.' }, 400);
  if (!res.ok) return json({ error: `The website answered with an error (${res.status}).` }, 502);
  const buf = new Uint8Array(await res.arrayBuffer());
  if (buf.length > MAX_BYTES) return json({ error: 'That page is too large to read.' }, 413);
  const html = new TextDecoder().decode(buf);
  const recipe = findRecipe(html);
  if (!recipe) return json({ error: 'No recipe was found on that page. You can still add it by hand with the link as the source.' }, 404);
  const site = /<meta[^>]+property\s*=\s*["']og:site_name["'][^>]*content\s*=\s*["']([^"']*)["']/i.exec(html)?.[1] || '';
  return json({ recipe: pick(recipe), url: finalUrl.href, site });
});
