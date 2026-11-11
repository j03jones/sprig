// send-invite: emails someone an invite to Sprig.
// 1. Makes a one-person invite code as the signed-in caller (so the database's own rules decide who may
//    invite whom: the admin can invite anyone, a restaurant owner only staff for their restaurant).
// 2. Asks Supabase Auth to send its "Invite user" email (through the project's SMTP, i.e. Resend). The
//    link signs the person in; the app then asks them to choose a password.
// No email keys live here: Supabase sends the email. Deploy with JWT verification ON.
const URL_ = Deno.env.get('SUPABASE_URL')!;
const ANON = Deno.env.get('SUPABASE_ANON_KEY')!;
const SERVICE = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const APP_RE = /^https:\/\/(recipes\.jonesridgekitchen\.com|[a-z0-9-]+\.github\.io)(\/[^#?]*)?$/i;

async function rest(path: string, init: RequestInit & { key: string; token?: string }) {
  const res = await fetch(`${URL_}${path}`, {
    ...init,
    headers: { apikey: init.key, Authorization: `Bearer ${init.token || init.key}`, 'Content-Type': 'application/json', ...(init.headers || {}) },
  });
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  return { ok: res.ok, status: res.status, data };
}
const msgOf = (d: any) => (d && (d.message || d.msg || d.error_description || d.error)) || '';

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'Use POST.' }, 405);
  const token = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  let body: any;
  try { body = await req.json(); } catch { return json({ error: 'Bad request.' }, 400); }

  const email = String(body.email || '').trim().toLowerCase();
  const name = String(body.name || '').trim().slice(0, 80);
  const kind = body.kind === 'restaurant' ? 'restaurant' : 'student';
  const appUrl = String(body.app_url || '');
  if (!EMAIL_RE.test(email)) return json({ error: 'Please enter a valid email address.' }, 400);
  if (!APP_RE.test(appUrl)) return json({ error: 'Unknown app address.' }, 400);

  // 1. the invite code, made as the caller
  const made = await rest('/rest/v1/rpc/create_invite', {
    method: 'POST', key: ANON, token,
    body: JSON.stringify({ p_kind: kind, p_restaurant: kind === 'restaurant' ? body.restaurant_id : null,
      p_member_role: body.member_role === 'owner' ? 'owner' : 'staff', p_max_uses: 1, p_days: 14 }),
  });
  if (!made.ok) return json({ error: msgOf(made.data) || 'You are not allowed to send this invite.' }, made.status === 401 ? 401 : 403);
  const code = String(made.data);
  await rest(`/rest/v1/invites?code=eq.${encodeURIComponent(code)}`, { method: 'PATCH', key: SERVICE, body: JSON.stringify({ email }) });

  // 2. the email
  const sent = await rest(`/auth/v1/invite?redirect_to=${encodeURIComponent(appUrl)}`, {
    method: 'POST', key: SERVICE,
    body: JSON.stringify({ email, data: { invite_code: code, display_name: name } }),
  });
  if (!sent.ok) {
    await rest(`/rest/v1/invites?code=eq.${encodeURIComponent(code)}`, { method: 'PATCH', key: SERVICE, body: JSON.stringify({ cancelled_at: new Date().toISOString() }) });
    const m = msgOf(sent.data);
    if (sent.status === 422 || /already been registered|already exists/i.test(m)) {
      return json({ error: 'That email already has an account. They can sign in, or use “Forgot password?”.' }, 409);
    }
    if (/seats/i.test(m) || /database error/i.test(m)) return json({ error: 'This restaurant has no free logins left. Raise its login limit first.' }, 409);
    if (sent.status === 429) return json({ error: 'Too many emails sent in the last hour. Try again later, or share the link or QR code instead.' }, 429);
    return json({ error: m || 'The email could not be sent.' }, 502);
  }

  // 3. if this answered an invite request, mark it handled (as the caller: only the admin can)
  if (body.request_id) {
    await rest(`/rest/v1/invite_requests?id=eq.${encodeURIComponent(body.request_id)}`, {
      method: 'PATCH', key: ANON, token, body: JSON.stringify({ status: 'invited', handled_at: new Date().toISOString() }),
    });
  }
  return json({ ok: true, code, email });
});
