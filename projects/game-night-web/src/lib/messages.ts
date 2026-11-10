// Human wording for the ?error= and ?notice= codes the auth and action routes redirect with.

export const ERRORS: Record<string, string> = {
  patreon_denied: "Patreon sign-in was cancelled. Nothing was shared.",
  patreon_state: "That sign-in link expired. Start again from the Sign in button.",
  patreon_failed: "Patreon didn't complete the sign-in. Try again in a minute.",
  signed_out: "Your session ended. Sign in again to continue.",
  discord_denied: "Discord linking was cancelled.",
  discord_state: "That Discord link expired. Start again from Link Discord.",
  discord_failed: "Discord didn't complete the link. Try again in a minute.",
  discord_taken: "That Discord account is already linked to a different Patreon account.",
  seat_full: "That episode's guaranteed seat was just taken. Pick another episode.",
  seat_already: "You've already claimed your guaranteed seat for this offseason.",
  seat_closed: "That episode isn't open for seat claims.",
  seat_tier: "Guaranteed seats are an Executive Producer benefit.",
  refresh_failed: "Patreon couldn't be reached to re-check your tier. Your last known tier still applies.",
};

export const NOTICES: Record<string, string> = {
  join_server: "Discord linked. Join the Phillies Therapy server to finish, then check again.",
  seat_claimed: "Seat claimed. We'll contact you on Discord before the show.",
  seat_released: "Seat released.",
  tier_refreshed: "Tier re-checked with Patreon.",
  saved: "Saved.",
};

export function first(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}
