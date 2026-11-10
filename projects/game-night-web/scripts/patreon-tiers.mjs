// Prints your Patreon campaign ID and tier prices, to fill in PATREON_CAMPAIGN_ID
// and confirm the PATREON_TIER_*_CENTS floors.
//
// The "Creator's Access Token" is shown on your client at
// https://www.patreon.com/portal/registration/register-clients
//
//   PowerShell:  $env:PATREON_CREATOR_TOKEN = "..." ; node scripts/patreon-tiers.mjs
//   bash:        PATREON_CREATOR_TOKEN=... node scripts/patreon-tiers.mjs

const token = process.env.PATREON_CREATOR_TOKEN;
if (!token) {
  console.error("Set PATREON_CREATOR_TOKEN to your client's Creator's Access Token first.");
  process.exit(1);
}

const url =
  "https://www.patreon.com/api/oauth2/v2/campaigns?include=tiers&" +
  new URLSearchParams({ "fields[campaign]": "vanity,patron_count", "fields[tier]": "title,amount_cents,published" });
const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
if (!res.ok) {
  console.error(`Patreon returned ${res.status}: ${await res.text()}`);
  process.exit(1);
}
const json = await res.json();
const tiers = new Map((json.included ?? []).filter((r) => r.type === "tier").map((t) => [t.id, t.attributes]));

for (const campaign of json.data ?? []) {
  console.log(`\nCampaign ${campaign.attributes?.vanity ?? ""}`);
  console.log(`  PATREON_CAMPAIGN_ID=${campaign.id}`);
  const ids = (campaign.relationships?.tiers?.data ?? []).map((t) => t.id);
  for (const id of ids) {
    const t = tiers.get(id);
    if (!t) continue;
    console.log(`  tier ${id}  ${String(t.amount_cents).padStart(6)} cents  ${t.title}${t.published ? "" : "  (unpublished)"}`);
  }
}
console.log("\nThe app maps tiers by price: set PATREON_TIER_MEMBER_CENTS / _PRODUCER_CENTS / _EXEC_CENTS to the three paid prices above.");
