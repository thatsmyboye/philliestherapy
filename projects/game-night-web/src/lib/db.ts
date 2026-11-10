import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { env } from "./env";

let client: SupabaseClient | null | undefined;

/** Service-role client for server code only. Null when Supabase isn't configured. */
export function db(): SupabaseClient | null {
  if (client !== undefined) return client;
  const url = env.supabaseUrl();
  const key = env.supabaseServiceKey();
  client = url && key ? createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } }) : null;
  return client;
}

export function requireDb(): SupabaseClient {
  const c = db();
  if (!c) throw new Error("Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)");
  return c;
}
