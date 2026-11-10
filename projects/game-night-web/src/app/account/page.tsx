import type { Metadata } from "next";
import Link from "next/link";
import { Flash } from "@/components/Flash";
import { AccessGate } from "@/components/Gate";
import { env } from "@/lib/env";
import { TIER_NAME, TIER_PRICE } from "@/lib/tiers";
import { discordReady, displayName, effectiveTier, getCurrentUser, isAdmin } from "@/lib/users";
import { recheckTier } from "./actions";

export const metadata: Metadata = { title: "Account" };
export const dynamic = "force-dynamic";

export default async function Account({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [user, search] = await Promise.all([getCurrentUser({ fresh: true }), searchParams]);

  if (!user) {
    return (
      <div className="stack">
        <h1 style={{ fontSize: "clamp(2rem, 7vw, 3.5rem)" }}>Account</h1>
        <Flash search={search} />
        <AccessGate user={null} next="/account" what="see your account" />
      </div>
    );
  }

  const tier = effectiveTier(user);
  const invite = env.discordInviteUrl();

  return (
    <div className="stack">
      <p className="light">Signed in</p>
      <h1 style={{ fontSize: "clamp(2rem, 7vw, 3.5rem)", overflowWrap: "anywhere" }}>{displayName(user)}</h1>
      <Flash search={search} />

      <div className="grid">
        <section className="card stack">
          <div className="row between">
            <h3>Patreon</h3>
            <span className={`badge badge-${tier}`}>
              {TIER_NAME[tier]}
              {tier > 0 ? ` · ${TIER_PRICE[tier]}` : ""}
            </span>
          </div>
          <p className="muted">
            {user.patreon_name ?? "Patreon member"}
            {isAdmin(user) ? ". Host account: every benefit is unlocked for testing." : tier === 0 ? ". No paid Phillies Therapy membership found." : "."}
          </p>
          <div className="row">
            <form action={recheckTier}>
              <button className="btn btn-sm btn-ghost">Re-check tier</button>
            </form>
            {tier < 3 && (
              <a className="btn btn-sm btn-blue" href={env.patreonJoinUrl()} target="_blank" rel="noreferrer">
                {tier === 0 ? "Join on Patreon" : "Upgrade"}
              </a>
            )}
          </div>
          <p className="small muted">Just pledged or changed tier? Re-check to pick it up right away.</p>
        </section>

        <section className="card stack">
          <div className="row between">
            <h3>Discord</h3>
            <span className={`badge ${discordReady(user) ? "" : "badge-0"}`}>
              {discordReady(user) ? "Linked" : user.discord_user_id ? "Not in server" : "Not linked"}
            </span>
          </div>
          {user.discord_user_id ? (
            <p className="muted">
              {user.discord_username}
              {user.discord_in_guild ? ", in the Phillies Therapy server." : ". Join the Phillies Therapy server to play."}
            </p>
          ) : (
            <p className="muted">Link Discord to play along and to be called into the contestant voice channel.</p>
          )}
          <div className="row">
            <a className="btn btn-sm btn-blue" href="/auth/discord?next=/account">
              {user.discord_user_id ? (user.discord_in_guild ? "Re-link Discord" : "Check again") : "Link Discord"}
            </a>
            {invite && !user.discord_in_guild && (
              <a className="btn btn-sm btn-ghost" href={invite} target="_blank" rel="noreferrer">
                Join the server
              </a>
            )}
          </div>
        </section>
      </div>

      <div className="row">
        <Link className="btn" href="/play">
          Play along
        </Link>
        {tier >= 3 && (
          <Link className="btn btn-ghost" href="/seat">
            Claim your seat
          </Link>
        )}
        <form action="/auth/logout" method="post">
          <button className="btn btn-ghost">Sign out</button>
        </form>
      </div>
    </div>
  );
}
