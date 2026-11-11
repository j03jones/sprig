// Public connection details for Sprig's hosted database (Supabase). The publishable key is designed to
// be public: the access rules live in the database (supabase/schema.sql). NEVER put the secret /
// service_role key here.
//
// Both are empty until Sprig has its own Supabase project (see supabase/README.md): the app then runs
// as an on-device recipe box, and the sign-in screens say accounts are not switched on yet.
export const SUPABASE_URL = '';
export const SUPABASE_KEY = '';
