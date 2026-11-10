import type { Metadata } from "next";
import { Flash } from "@/components/Flash";
import { AccessGate, needsGate } from "@/components/Gate";
import { requireDb } from "@/lib/db";
import { env } from "@/lib/env";
import { formatAirDate, listEpisodes } from "@/lib/episodes";
import { effectiveTier, getCurrentUser } from "@/lib/users";
import { claimSeat, releaseSeat } from "./actions";

export const metadata: Metadata = { title: "Guaranteed seat" };
export const dynamic = "force-dynamic";

export default async function Seat({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [user, search] = await Promise.all([getCurrentUser({ fresh: true }), searchParams]);

  const heading = (
    <>
      <p className="light">Executive Producer</p>
      <h1 style={{ fontSize: "clamp(2rem, 7vw, 3.5rem)" }}>Your seat</h1>
    </>
  );

  if (needsGate(user) || !user) {
    return (
      <div className="stack">
        {heading}
        <AccessGate user={user} next="/seat" what="claim your seat" />
      </div>
    );
  }

  if (effectiveTier(user) < 3) {
    return (
      <div className="stack">
        {heading}
        <div className="card stack">
          <h2>An Executive Producer benefit</h2>
          <p className="muted">
            The $25 tier comes with one guaranteed contestant seat per offseason. Members at $5 and up are entered in the contestant lottery
            for every episode.
          </p>
          <div className="row">
            <a className="btn" href={env.patreonJoinUrl()} target="_blank" rel="noreferrer">
              Upgrade on Patreon
            </a>
            <a className="btn btn-ghost" href="/account">
              Re-check my tier
            </a>
          </div>
        </div>
      </div>
    );
  }

  const [episodes, claimsRes] = await Promise.all([
    listEpisodes(),
    requireDb().from("gn_seat_claims").select("episode_id, user_id").eq("season", env.season()),
  ]);
  const claims = (claimsRes.data ?? []) as { episode_id: number; user_id: string }[];
  const mine = claims.find((c) => c.user_id === user.id);
  const taken = (id: number) => claims.filter((c) => c.episode_id === id).length;
  const myEpisode = mine ? episodes.find((e) => e.id === mine.episode_id) : null;

  return (
    <div className="stack">
      {heading}
      <Flash search={search} />
      <p className="muted">One guaranteed contestant seat per offseason, first come. On your episode you also pick the Seventh Inning Stretch option.</p>

      {myEpisode && (
        <div className="card card-cream stack">
          <span className="band band-blue">Your seat</span>
          <h2>
            Episode {myEpisode.number}: {myEpisode.title}
          </h2>
          <p>{formatAirDate(myEpisode.airs_at)}. We&apos;ll reach you on Discord to confirm and sound-check before the show.</p>
          {myEpisode.status === "upcoming" && (
            <form action={releaseSeat}>
              <button className="btn btn-sm btn-ghost" style={{ color: "var(--maroon)", boxShadow: "inset 0 0 0 2px rgba(99,34,55,.3)" }}>
                Release this seat
              </button>
            </form>
          )}
        </div>
      )}

      <div className="card">
        {episodes.map((e) => {
          const left = Math.max(0, e.exec_seats - taken(e.id));
          const claimable = !mine && e.status === "upcoming" && left > 0;
          return (
            <div key={e.id} className="episode">
              <span className="num">{e.number}</span>
              <span className="row between">
                <span className="title">{e.title}</span>
                {claimable ? (
                  <form action={claimSeat}>
                    <input type="hidden" name="episode_id" value={e.id} />
                    <button className="btn btn-sm">Claim seat</button>
                  </form>
                ) : (
                  <span className="badge badge-0">
                    {mine?.episode_id === e.id ? "Yours" : e.exec_seats === 0 ? "By qualification" : e.status !== "upcoming" ? "Closed" : left === 0 ? "Taken" : "Open"}
                  </span>
                )}
              </span>
              <span className="muted small">{formatAirDate(e.airs_at)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
