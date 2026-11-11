// request-invite: someone without an account asks for an invite. Saves the request (request_invite) and,
// the first time that person asks, emails the admin through Resend so nobody has to keep checking Admin tools.
// Open to signed-out visitors, so deploy with JWT verification OFF. The email always goes to the admin
// address in app_settings, never to an address the visitor typed.
// Needs the RESEND_API_KEY secret (Edge Functions > Secrets). Without it the request is still saved.
const URL_ = Deno.env.get('SUPABASE_URL')!;
const ANON = Deno.env.get('SUPABASE_ANON_KEY')!;
const SERVICE = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const RESEND = Deno.env.get('RESEND_API_KEY') || '';
const FROM = 'Sprig <hello@mail.jonesridgekitchen.com>';
const APP = 'https://j03jones.github.io/sprig/';
const MAX_EMAILS_PER_HOUR = 10;   // a burst of requests gets one email each up to this, then they wait in Admin tools
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));

async function rest(path: string, key: string, init: RequestInit = {}) {
  const res = await fetch(`${URL_}${path}`, {
    ...init,
    headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', ...(init.headers || {}) },
  });
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  return { ok: res.ok, status: res.status, data };
}

/** Resend with an idempotency key (a retry never sends twice) and a few retries on rate limits / outages. */
async function sendEmail(payload: Record<string, unknown>, idempotencyKey: string) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${RESEND}`, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(payload),
    });
    if (res.ok) return true;
    if (res.status !== 429 && res.status < 500) { console.error('resend', res.status, await res.text()); return false; }
    await new Promise((r) => setTimeout(r, 800 * 2 ** attempt));
  }
  return false;
}

const ABOUT: Record<string, string> = { student: 'A culinary student', restaurant: 'From a restaurant', other: 'Something else' };

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'Use POST.' }, 405);
  let b: any;
  try { b = await req.json(); } catch { return json({ error: 'Bad request.' }, 400); }
  const name = String(b.name || '').trim().slice(0, 80);
  const email = String(b.email || '').trim().toLowerCase();
  const about = ['student', 'restaurant', 'other'].includes(b.about) ? b.about : 'other';
  const note = String(b.note || '').trim().slice(0, 500);

  const saved = await rest('/rest/v1/rpc/request_invite', ANON, {
    method: 'POST', body: JSON.stringify({ p_name: name, p_email: email, p_about: about, p_note: note }),
  });
  if (!saved.ok) return json({ error: (saved.data && saved.data.message) || 'Could not send the request.' }, 400);
  const isNew = saved.data === true;
  let emailed = false;

  if (isNew && RESEND) {
    const settings = await rest('/rest/v1/app_settings?select=admin_email', SERVICE);
    const adminEmail = settings.ok && settings.data?.[0]?.admin_email;
    const since = new Date(Date.now() - 3600_000).toISOString();
    const recent = await rest(`/rest/v1/invite_requests?select=id&created_at=gte.${encodeURIComponent(since)}`, SERVICE);
    const burst = recent.ok && Array.isArray(recent.data) && recent.data.length > MAX_EMAILS_PER_HOUR;
    if (adminEmail && !burst) {
      const waiting = await rest('/rest/v1/invite_requests?select=id&status=eq.waiting', SERVICE);
      const n = Array.isArray(waiting.data) ? waiting.data.length : 1;
      const admin = `${APP}#/admin`;
      const html = `<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5;color:#14181d;max-width:520px">
<p style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#17835a;font-weight:700;margin:0 0 12px">Sprig</p>
<h1 style="font-size:20px;margin:0 0 12px">${esc(name)} asked for an invite</h1>
<p style="margin:0 0 4px"><strong>Email:</strong> ${esc(email)}</p>
<p style="margin:0 0 4px"><strong>They are:</strong> ${esc(ABOUT[about])}</p>
${note ? `<p style="margin:12px 0;padding:10px 12px;background:#f2f4f3;border-radius:8px">“${esc(note)}”</p>` : ''}
<p style="margin:20px 0"><a href="${admin}" style="display:inline-block;background:#2850f0;color:#fff;text-decoration:none;font-weight:600;padding:12px 22px;border-radius:8px">Open Admin tools</a></p>
<p style="font-size:13px;color:#5d6762">${n === 1 ? 'This is the only request waiting.' : `${n} requests are waiting.`} In Admin tools, tap “Send student invite” or “Dismiss”.</p>
</div>`;
      const text = `${name} asked for an invite.\nEmail: ${email}\nThey are: ${ABOUT[about]}\n${note ? `Note: ${note}\n` : ''}\nOpen Admin tools: ${admin}\n`;
      emailed = await sendEmail({
        from: FROM, to: [adminEmail], reply_to: email,
        subject: `Invite request from ${name}`, html, text,
      }, `invite-request-${email}-${new Date().toISOString().slice(0, 10)}`);
    }
  }
  return json({ ok: true, new: isNew, emailed });
});
