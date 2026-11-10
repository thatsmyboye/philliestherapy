import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Flash } from "@/components/Flash";
import { requireDb } from "@/lib/db";
import { env } from "@/lib/env";
import { listEpisodes } from "@/lib/episodes";
import { getLive } from "@/lib/live";
import { isoToEasternLocal } from "@/lib/time";
import { TIER_NAME, type Tier } from "@/lib/tiers";
import { getCurrentUser, isAdmin } from "@/lib/users";
import { removeClaim, saveEpisode } from "./actions";

export const metadata: Metadata = { title: "Host" };
export const dynamic = "force-dynamic";

type ClaimRow = {
  id: string;
  episode_id: number;
  created_at: string;
  gn_users: { display_name: string | null; discord_username: string | null; patreon_name: string | null } | { display_name: string | null; discord_username: string | null; patreon_name: string | null }[] | null;
};

export default async function Admin({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [user, search] = await Promise.all([getCurrentUser(), searchParams]);
  if (!isAdmin(user)) notFound();

  const client = requireDb();
  const [episodes, live, claimsRes, usersRes] = await Promise.all([
    listEpisodes(),
    getLive(),
    client.from("gn_seat_claims").select("id, episode_id, created_at, gn_users(display_name, discord_username, patreon_name)").eq("season", env.season()).order("created_at"),
    client.from("gn_users").select("tier, discord_in_guild"),
  ]);
  const claims = (claimsRes.data ?? []) as unknown as ClaimRow[];
  const users = (usersRes.data ?? []) as { tier: Tier; discord_in_guild: boolean }[];
  const epNumber = (id: number) => episodes.find((e) => e.id === id)?.number ?? "?";

  return (
    <div className="stack-lg">
      <div className="stack">
        <p className="light">Host</p>
        <h1 style={{ fontSize: "clamp(2rem, 7vw, 3.5rem)" }}>Control room</h1>
        <Flash search={search} />
      </div>

      <section className="grid">
        <div className="card stack">
          <h3>Overlay link</h3>
          <p>
            <span className={`dot${live.status !== "idle" ? " on" : ""}`} />
            {live.status === "idle" ? "No question on screen" : `${live.status}: ${live.category ?? ""} / ${live.difficulty ?? ""}`}
          </p>
          <p className="small muted">{live.question ?? "The overlay posts here whenever a question, the clock or the answer changes."}</p>
        </div>
        <div className="card stack">
          <h3>Members signed in</h3>
          <div>
            {([3, 2, 1, 0] as Tier[]).map((t) => (
              <div key={t} className="leader-row">
                <span>{TIER_NAME[t]}</span>
                <b>{users.filter((u) => u.tier === t).length}</b>
              </div>
            ))}
          </div>
          <p className="small muted">{users.filter((u) => u.discord_in_guild).length} with Discord linked and in the server.</p>
        </div>
      </section>

      <section className="stack">
        <h2>Episodes</h2>
        <p className="muted small">Times are Eastern. Set an episode to Live on show night and Done afterwards; seat claims close once it leaves Upcoming.</p>
        {episodes.map((e) => (
          <form key={e.id} action={saveEpisode} className="card form-grid">
            <input type="hidden" name="id" value={e.id} />
            <label>
              Episode {e.number} title
              <input name="title" defaultValue={e.title} maxLength={120} required />
            </label>
            <label>
              Theme
              <input name="theme" defaultValue={e.theme ?? ""} maxLength={200} />
            </label>
            <label>
              Airs (ET)
              <input name="airs_at" type="datetime-local" defaultValue={isoToEasternLocal(e.airs_at)} />
            </label>
            <label>
              Status
              <select name="status" defaultValue={e.status}>
                <option value="upcoming">Upcoming</option>
                <option value="live">Live</option>
                <option value="done">Done</option>
              </select>
            </label>
            <label>
              Guaranteed seats
              <input name="exec_seats" type="number" min={0} max={4} defaultValue={e.exec_seats} />
            </label>
            <button className="btn btn-sm">Save</button>
          </form>
        ))}
      </section>

      <section className="stack">
        <h2>Guaranteed seat claims</h2>
        {claims.length === 0 ? (
          <p className="muted">No Executive Producer has claimed a seat yet.</p>
        ) : (
          <div className="card table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th className="left">Discord</th>
                  <th>Episode</th>
                  <th>Claimed</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {claims.map((c) => {
                  const u = Array.isArray(c.gn_users) ? c.gn_users[0] : c.gn_users;
                  return (
                    <tr key={c.id}>
                      <td className="name">{u?.display_name ?? u?.patreon_name ?? "Member"}</td>
                      <td className="left">{u?.discord_username ?? ""}</td>
                      <td>{epNumber(c.episode_id)}</td>
                      <td>{new Date(c.created_at).toLocaleDateString("en-US", { timeZone: "America/New_York" })}</td>
                      <td>
                        <form action={removeClaim}>
                          <input type="hidden" name="id" value={c.id} />
                          <button className="btn btn-sm btn-ghost">Remove</button>
                        </form>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
