# Game Night web app

The members' side of Phillies Therapy Game Night: sign in with Patreon, link Discord, play along with every question live, and (for Executive Producers) claim a guaranteed contestant seat. Next.js on Vercel, data in the bot's Supabase project.

| Page | Who | What |
|---|---|---|
| `/` | Public | Next episode, how the game works, tier benefits, schedule |
| `/standings` | Public | Hot Stove League standings, pushed from the overlay |
| `/play` | Signed in, Discord linked and in the server | Live question, clock, one final answer, results, Bullpen leaderboard |
| `/seat` | $25 Executive Producer | Claim the one guaranteed seat per offseason |
| `/account` | Signed in | Tier, Discord link, re-check tier, sign out |
| `/admin` | Discord IDs in `ADMIN_DISCORD_IDS` | Episode dates and status, seat claims, overlay link status |

## How access is decided

- **Patreon is the login and the source of truth for tier.** Scopes: `identity identity.memberships`. The tier comes from the list price of the member's `currently_entitled_tiers`, compared against the `PATREON_TIER_*_CENTS` floors, so annual and gifted memberships count and lapsed ones don't.
- **Discord is a required link, not a login.** Scopes: `identify guilds.members.read`, used once to read the member's name and confirm they're in the server (`DISCORD_GUILD_ID`). The Discord token is discarded afterwards.
- The tier is re-read from Patreon when it's more than 12 hours old (and on demand from `/account`). If Patreon is unreachable the last known tier stands; if the member revoked access, benefits stop until they sign in again.
- Sessions are a signed, HTTP-only cookie. The Patreon refresh token is stored AES-256-GCM encrypted. Both use `SESSION_SECRET`; changing it signs everyone out.
- Accounts listed in `ADMIN_DISCORD_IDS` get every benefit, so the host can test each page.

## How live play-along works

The overlay on the streaming PC only makes outbound calls; nothing on it is exposed.

1. The host shows a question. The overlay POSTs the category, difficulty, text and clock to `/api/ingest` (no answer).
2. Players on `/play` see it through Supabase Realtime (with polling as a fallback) and submit one answer, timestamped by the server. Answers after the clock are refused.
3. The host reveals the answer (or presses HIT/OUT). The overlay sends the answer and alternates; the app grades every submission with the same matcher the overlay uses for Twitch `!swing`.
4. The earliest correct answer from a $5+ member earns the question's base value. The overlay adds it to its Bullpen board. Free members can swing and see whether they were right, but don't score.
5. Standings are pushed whenever they change on the overlay.

Stream delay: set `cloud.delaySeconds` in the overlay's `config.json` so questions reach the web app when viewers actually hear them.

## Setup

1. **Supabase**: run `supabase/schema.sql` once in the SQL editor of the bot's project. It only creates `gn_`-prefixed tables.
2. **Patreon**: as the campaign owner, create a client at <https://www.patreon.com/portal/registration/register-clients>. Redirect URI: `{APP_URL}/auth/patreon/callback`. Run `node scripts/patreon-tiers.mjs` to get the campaign ID and check tier prices.
3. **Discord**: in the developer portal (the bot's application works), add the redirect `{APP_URL}/auth/discord/callback` under OAuth2.
4. **Vercel**: new project from this repo with **Root Directory** `projects/game-night-web`. Add every variable in `.env.example`. The repo's root `vercel.json` belongs to the Sequence Baseball page and is not used here.
5. **Overlay**: in `Game Night/overlay/config.json`, set `cloud.enabled: true`, `cloud.url` to the app's URL and `cloud.secret` to `OVERLAY_INGEST_SECRET`. The control panel header shows `Web app: live`.
6. Sign in, link Discord, add your Discord user ID to `ADMIN_DISCORD_IDS`, then set episode dates at `/admin`.

## Local development

```
cp .env.example .env.local   # fill in values; APP_URL=http://localhost:3000
npm install
npm run dev
npm test                     # matcher, grading, tier mapping, session crypto, time zones
```

Register `http://localhost:3000/auth/patreon/callback` and `http://localhost:3000/auth/discord/callback` as extra redirect URIs to sign in locally. Without Supabase configured the public pages still render with the default schedule.

## Not in this version

Contestant lottery entry and Pinch Hitter question submissions (both run outside the app for now), Twitch/YouTube account linking, and Snapshot images on `/play` (Snapshot questions show their text only).
