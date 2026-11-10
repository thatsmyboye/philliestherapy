import { cookies } from "next/headers";
import { env } from "./env";
import { randomToken, safeEqual, seal, unseal } from "./secure";

const SESSION_COOKIE = "gn_session";
const SESSION_DAYS = 30;

function secureCookies(): boolean {
  return env.appUrl().startsWith("https://");
}

export async function createSession(userId: string): Promise<void> {
  const exp = Date.now() + SESSION_DAYS * 86_400_000;
  (await cookies()).set(SESSION_COOKIE, seal(`${userId}.${exp}`, env.sessionSecret()), {
    httpOnly: true,
    sameSite: "lax",
    secure: secureCookies(),
    path: "/",
    maxAge: SESSION_DAYS * 86_400,
  });
}

export async function readSessionUserId(): Promise<string | null> {
  const raw = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!raw || !process.env.SESSION_SECRET) return null;
  const payload = unseal(raw, env.sessionSecret());
  if (!payload) return null;
  const [userId, exp] = payload.split(".");
  if (!userId || !(Number(exp) > Date.now())) return null;
  return userId;
}

export async function clearSession(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
}

// --- OAuth state: a random value in a short-lived cookie, echoed back by the provider ---

export async function startOAuthState(provider: "patreon" | "discord", next: string | null): Promise<string> {
  const state = randomToken();
  (await cookies()).set(`gn_oauth_${provider}`, JSON.stringify({ state, next: safeNext(next) }), {
    httpOnly: true,
    sameSite: "lax",
    secure: secureCookies(),
    path: "/",
    maxAge: 600,
  });
  return state;
}

/** Returns the post-login path if `state` matches the cookie, otherwise null. Single use. */
export async function finishOAuthState(provider: "patreon" | "discord", state: string | null): Promise<string | null> {
  const jar = await cookies();
  const name = `gn_oauth_${provider}`;
  const raw = jar.get(name)?.value;
  jar.delete(name);
  if (!raw || !state) return null;
  try {
    const saved = JSON.parse(raw) as { state: string; next: string };
    return safeEqual(saved.state, state) ? safeNext(saved.next) : null;
  } catch {
    return null;
  }
}

/** Only same-site paths, so the login redirect can't be used to bounce people elsewhere. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/account";
  return next;
}
