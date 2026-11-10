// Patreon tier mapping. Pure functions: no env, no network.

export type Tier = 0 | 1 | 2 | 3;

export const TIER_NAME: Record<Tier, string> = {
  0: "Free",
  1: "Member",
  2: "Producer",
  3: "Executive Producer",
};

export const TIER_PRICE: Record<Tier, string> = { 0: "$0", 1: "$5", 2: "$12", 3: "$25" };

export interface TierFloors {
  member: number;
  producer: number;
  exec: number;
}

export function tierFromCents(cents: number, floors: TierFloors): Tier {
  if (cents >= floors.exec) return 3;
  if (cents >= floors.producer) return 2;
  if (cents >= floors.member) return 1;
  return 0;
}

interface JsonApiResource {
  type: string;
  id: string;
  attributes?: Record<string, unknown>;
  relationships?: Record<string, { data?: { id: string; type: string } | { id: string; type: string }[] | null }>;
}

export interface PatreonIdentity {
  data: JsonApiResource;
  included?: JsonApiResource[];
}

export interface Membership {
  patreonUserId: string;
  name: string | null;
  patronStatus: string | null;
  /** List price of the highest tier Patreon says this member is entitled to. */
  entitledCents: number;
}

/**
 * Reads a `/api/oauth2/v2/identity` response that included
 * `memberships.currently_entitled_tiers` and `memberships.campaign`.
 * Entitlement comes from `currently_entitled_tiers` (what Patreon says the member
 * should have access to right now), so gifted and annual memberships count and
 * lapsed ones do not.
 */
export function readMembership(identity: PatreonIdentity, campaignId: string | null): Membership {
  const included = identity.included ?? [];
  const tierCents = new Map<string, number>();
  for (const r of included) {
    if (r.type === "tier") tierCents.set(r.id, Number(r.attributes?.amount_cents) || 0);
  }

  let entitledCents = 0;
  let patronStatus: string | null = null;
  for (const m of included) {
    if (m.type !== "member") continue;
    const campaign = m.relationships?.campaign?.data;
    const memberCampaignId = campaign && !Array.isArray(campaign) ? campaign.id : null;
    if (campaignId && memberCampaignId !== campaignId) continue;

    const tiers = m.relationships?.currently_entitled_tiers?.data;
    const tierIds = Array.isArray(tiers) ? tiers.map((t) => t.id) : [];
    const cents = Math.max(0, ...tierIds.map((id) => tierCents.get(id) ?? 0));
    if (cents >= entitledCents) {
      entitledCents = cents;
      patronStatus = (m.attributes?.patron_status as string | null) ?? patronStatus;
    }
  }

  return {
    patreonUserId: identity.data.id,
    name: (identity.data.attributes?.full_name as string | undefined) ?? null,
    patronStatus,
    entitledCents,
  };
}
