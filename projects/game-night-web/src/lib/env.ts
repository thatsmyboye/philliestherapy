// Server-side configuration. Read lazily so `next build` works without secrets.

function required(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing environment variable ${name}`);
  return v;
}

function int(name: string, fallback: number): number {
  const n = Number(process.env[name]);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export const env = {
  appUrl: () => (process.env.APP_URL || "http://localhost:3000").replace(/\/+$/, ""),
  sessionSecret: () => {
    const s = required("SESSION_SECRET");
    if (s.length < 32) throw new Error("SESSION_SECRET must be at least 32 characters");
    return s;
  },
  season: () => process.env.SEASON || "2026-27",

  patreonClientId: () => required("PATREON_CLIENT_ID"),
  patreonClientSecret: () => required("PATREON_CLIENT_SECRET"),
  patreonCampaignId: () => process.env.PATREON_CAMPAIGN_ID || null,
  patreonJoinUrl: () => process.env.PATREON_JOIN_URL || "https://www.patreon.com/",
  tierFloors: () => ({
    member: int("PATREON_TIER_MEMBER_CENTS", 500),
    producer: int("PATREON_TIER_PRODUCER_CENTS", 1200),
    exec: int("PATREON_TIER_EXEC_CENTS", 2500),
  }),

  discordClientId: () => required("DISCORD_CLIENT_ID"),
  discordClientSecret: () => required("DISCORD_CLIENT_SECRET"),
  discordGuildId: () => required("DISCORD_GUILD_ID"),
  discordInviteUrl: () => process.env.DISCORD_INVITE_URL || null,
  adminDiscordIds: () =>
    (process.env.ADMIN_DISCORD_IDS || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),

  supabaseUrl: () => process.env.SUPABASE_URL || null,
  supabaseServiceKey: () => process.env.SUPABASE_SERVICE_ROLE_KEY || null,

  ingestSecret: () => process.env.OVERLAY_INGEST_SECRET || null,
};
