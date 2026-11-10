import { db, requireDb } from "./db";
import { env } from "./env";
import { fetchPatreonMembership, PatreonGrantError, refreshPatreonTokens, type PatreonTokens } from "./patreon";
import { decrypt, encrypt } from "./secure";
import { readSessionUserId } from "./session";
import { tierFromCents, type Tier } from "./tiers";
import type { DiscordProfile } from "./discord";

export interface User {
  id: string;
  patreon_user_id: string;
  patreon_name: string | null;
  tier: Tier;
  patron_status: string | null;
  entitled_cents: number;
  tier_checked_at: string | null;
  patreon_refresh_token_enc: string | null;
  discord_user_id: string | null;
  discord_username: string | null;
  discord_in_guild: boolean;
  display_name: string | null;
}

const TIER_MAX_AGE_MS = 12 * 3_600_000;

export function isAdmin(user: User | null): boolean {
  return !!user?.discord_user_id && env.adminDiscordIds().includes(user.discord_user_id);
}

/** Admins get every benefit so the host can test each page without pledging to themself. */
export function effectiveTier(user: User): Tier {
  return isAdmin(user) ? 3 : user.tier;
}

/** Participation needs a linked Discord account that is in the server. */
export function discordReady(user: User): boolean {
  return !!user.discord_user_id && user.discord_in_guild;
}

export function displayName(user: User): string {
  return user.display_name || user.discord_username || user.patreon_name || "Member";
}

/**
 * The signed-in user, or null. With `fresh`, the Patreon tier is re-read when the
 * stored value is older than 12 hours, so a cancelled pledge stops unlocking benefits.
 */
export async function getCurrentUser(opts: { fresh?: boolean } = {}): Promise<User | null> {
  const id = await readSessionUserId();
  const client = db();
  if (!id || !client) return null;
  const { data } = await client.from("gn_users").select("*").eq("id", id).maybeSingle();
  if (!data) return null;
  const user = data as User;
  if (!opts.fresh) return user;
  const age = user.tier_checked_at ? Date.now() - Date.parse(user.tier_checked_at) : Infinity;
  return age > TIER_MAX_AGE_MS ? refreshTier(user) : user;
}

/** Create or update the user after a Patreon sign-in. Returns the user id. */
export async function upsertFromPatreon(tokens: PatreonTokens): Promise<string> {
  const m = await fetchPatreonMembership(tokens.accessToken);
  const now = new Date().toISOString();
  const { data, error } = await requireDb()
    .from("gn_users")
    .upsert(
      {
        patreon_user_id: m.patreonUserId,
        patreon_name: m.name,
        tier: tierFromCents(m.entitledCents, env.tierFloors()),
        patron_status: m.patronStatus,
        entitled_cents: m.entitledCents,
        tier_checked_at: now,
        patreon_refresh_token_enc: encrypt(tokens.refreshToken, env.sessionSecret()),
        last_login_at: now,
      },
      { onConflict: "patreon_user_id" }
    )
    .select("id, display_name")
    .single();
  if (error) throw new Error(`Could not save user: ${error.message}`);
  if (!data.display_name && m.name) {
    await requireDb().from("gn_users").update({ display_name: m.name }).eq("id", data.id);
  }
  return data.id as string;
}

/** Re-read the member's tier from Patreon using the stored refresh token. */
export async function refreshTier(user: User): Promise<User> {
  const client = requireDb();
  const stored = user.patreon_refresh_token_enc && decrypt(user.patreon_refresh_token_enc, env.sessionSecret());
  const now = new Date().toISOString();
  let patch: Partial<User>;
  try {
    if (!stored) throw new PatreonGrantError("No stored Patreon grant");
    const tokens = await refreshPatreonTokens(stored);
    const m = await fetchPatreonMembership(tokens.accessToken);
    patch = {
      patreon_name: m.name,
      tier: tierFromCents(m.entitledCents, env.tierFloors()),
      patron_status: m.patronStatus,
      entitled_cents: m.entitledCents,
      tier_checked_at: now,
      // Patreon rotates refresh tokens; keep the new one.
      patreon_refresh_token_enc: encrypt(tokens.refreshToken, env.sessionSecret()),
    };
  } catch (err) {
    // Patreon being unreachable shouldn't lock members out mid-show: keep the last
    // known tier and try again next time. A rejected grant means access was revoked,
    // so benefits stop until they sign in again.
    if (!(err instanceof PatreonGrantError)) return user;
    patch = { tier: 0, patron_status: null, entitled_cents: 0, tier_checked_at: now, patreon_refresh_token_enc: null };
  }
  await client.from("gn_users").update(patch).eq("id", user.id);
  return { ...user, ...patch };
}

export type LinkResult = "ok" | "taken";

export async function linkDiscord(userId: string, profile: DiscordProfile): Promise<LinkResult> {
  const client = requireDb();
  const { data: other } = await client
    .from("gn_users")
    .select("id")
    .eq("discord_user_id", profile.id)
    .neq("id", userId)
    .maybeSingle();
  if (other) return "taken";
  const { error } = await client
    .from("gn_users")
    .update({
      discord_user_id: profile.id,
      discord_username: profile.username,
      discord_in_guild: profile.inGuild,
      discord_linked_at: new Date().toISOString(),
      display_name: profile.displayName,
    })
    .eq("id", userId);
  if (error) return error.code === "23505" ? "taken" : Promise.reject(new Error(error.message));
  return "ok";
}
