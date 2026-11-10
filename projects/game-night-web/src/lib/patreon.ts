import { env } from "./env";
import { readMembership, type Membership, type PatreonIdentity } from "./tiers";

const AUTHORIZE_URL = "https://www.patreon.com/oauth2/authorize";
const TOKEN_URL = "https://www.patreon.com/api/oauth2/token";
const IDENTITY_URL = "https://www.patreon.com/api/oauth2/v2/identity";

export function patreonRedirectUri(): string {
  return `${env.appUrl()}/auth/patreon/callback`;
}

export function patreonAuthorizeUrl(state: string): string {
  const q = new URLSearchParams({
    response_type: "code",
    client_id: env.patreonClientId(),
    redirect_uri: patreonRedirectUri(),
    scope: "identity identity.memberships",
    state,
  });
  return `${AUTHORIZE_URL}?${q}`;
}

export interface PatreonTokens {
  accessToken: string;
  refreshToken: string;
}

/** Thrown when Patreon rejects the grant itself (revoked or expired), as opposed to being unreachable. */
export class PatreonGrantError extends Error {}

async function tokenRequest(params: Record<string, string>): Promise<PatreonTokens> {
  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      ...params,
      client_id: env.patreonClientId(),
      client_secret: env.patreonClientSecret(),
    }),
    cache: "no-store",
  });
  if (res.status === 400 || res.status === 401) throw new PatreonGrantError(`Patreon rejected the grant (${res.status})`);
  if (!res.ok) throw new Error(`Patreon token endpoint returned ${res.status}`);
  const json = (await res.json()) as { access_token?: string; refresh_token?: string };
  if (!json.access_token || !json.refresh_token) throw new Error("Patreon token response was missing tokens");
  return { accessToken: json.access_token, refreshToken: json.refresh_token };
}

export function exchangePatreonCode(code: string): Promise<PatreonTokens> {
  return tokenRequest({ grant_type: "authorization_code", code, redirect_uri: patreonRedirectUri() });
}

export function refreshPatreonTokens(refreshToken: string): Promise<PatreonTokens> {
  return tokenRequest({ grant_type: "refresh_token", refresh_token: refreshToken });
}

export async function fetchPatreonMembership(accessToken: string): Promise<Membership> {
  const q = new URLSearchParams({
    include: "memberships,memberships.campaign,memberships.currently_entitled_tiers",
    "fields[user]": "full_name",
    "fields[member]": "patron_status,currently_entitled_amount_cents",
    "fields[tier]": "title,amount_cents",
  });
  const res = await fetch(`${IDENTITY_URL}?${q}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (res.status === 401) throw new PatreonGrantError("Patreon access token rejected");
  if (!res.ok) throw new Error(`Patreon identity endpoint returned ${res.status}`);
  return readMembership((await res.json()) as PatreonIdentity, env.patreonCampaignId());
}
