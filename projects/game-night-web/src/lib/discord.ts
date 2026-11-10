import { env } from "./env";

const API = "https://discord.com/api/v10";

export function discordRedirectUri(): string {
  return `${env.appUrl()}/auth/discord/callback`;
}

export function discordAuthorizeUrl(state: string): string {
  const q = new URLSearchParams({
    response_type: "code",
    client_id: env.discordClientId(),
    redirect_uri: discordRedirectUri(),
    scope: "identify guilds.members.read",
    state,
    prompt: "consent",
  });
  return `https://discord.com/oauth2/authorize?${q}`;
}

export async function exchangeDiscordCode(code: string): Promise<string> {
  const res = await fetch(`${API}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: discordRedirectUri(),
      client_id: env.discordClientId(),
      client_secret: env.discordClientSecret(),
    }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Discord token endpoint returned ${res.status}`);
  const json = (await res.json()) as { access_token?: string };
  if (!json.access_token) throw new Error("Discord token response was missing an access token");
  return json.access_token;
}

export interface DiscordProfile {
  id: string;
  username: string;
  /** Server nickname, then global display name, then username. */
  displayName: string;
  inGuild: boolean;
}

/**
 * Who the member is and whether they're in the Phillies Therapy server.
 * The access token is used for these two calls and then discarded.
 */
export async function fetchDiscordProfile(accessToken: string): Promise<DiscordProfile> {
  const headers = { Authorization: `Bearer ${accessToken}` };
  const userRes = await fetch(`${API}/users/@me`, { headers, cache: "no-store" });
  if (!userRes.ok) throw new Error(`Discord user endpoint returned ${userRes.status}`);
  const user = (await userRes.json()) as { id: string; username: string; global_name?: string | null };

  const memberRes = await fetch(`${API}/users/@me/guilds/${env.discordGuildId()}/member`, { headers, cache: "no-store" });
  let inGuild = false;
  let nick: string | null = null;
  if (memberRes.ok) {
    inGuild = true;
    nick = ((await memberRes.json()) as { nick?: string | null }).nick ?? null;
  } else if (memberRes.status !== 404) {
    throw new Error(`Discord guild member endpoint returned ${memberRes.status}`);
  }

  return { id: user.id, username: user.username, displayName: nick || user.global_name || user.username, inGuild };
}
