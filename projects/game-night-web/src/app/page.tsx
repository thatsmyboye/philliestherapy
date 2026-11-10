import Link from "next/link";
import { Flash } from "@/components/Flash";
import { env } from "@/lib/env";
import { formatAirDate, listEpisodes, pickNextEpisode } from "@/lib/episodes";
import { TIER_NAME, TIER_PRICE, type Tier } from "@/lib/tiers";
import { effectiveTier, getCurrentUser } from "@/lib/users";

export const dynamic = "force-dynamic";

const BENEFITS: Record<Tier, string[]> = {
  0: ["Watch the stream", "Play along in the Bullpen"],
  1: ["Everything in Free", "Score on the Bullpen leaderboard", "Contestant lottery entry"],
  2: ["Everything in Member", "3× lottery weight", "Submit Pinch Hitter questions", "Your name on the end screen"],
  3: ["Everything in Producer", "One guaranteed contestant seat per offseason", "Pick the Seventh Inning Stretch on your episode"],
};

const HITS = [
  { label: "Single", bases: "1", cls: "diff-Single" },
  { label: "Double", bases: "2", cls: "diff-Double" },
  { label: "Triple", bases: "3", cls: "diff-Triple" },
  { label: "Home Run", bases: "4", cls: "diff-HR" },
];

export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [user, episodes, search] = await Promise.all([getCurrentUser(), listEpisodes(), searchParams]);
  const next = pickNextEpisode(episodes);
  const myTier = user ? effectiveTier(user) : null;

  return (
    <div className="stack-lg">
      <section className="hero">
        <Flash search={search} />
        <p className="light" style={{ marginTop: 16 }}>Phillies Therapy presents</p>
        <h1>
          Game Night
          <small>Trivia is the at-bat</small>
        </h1>
        <p className="lede">
          Three contestants, three innings. Pick a category and a difficulty: get it right and that&apos;s your hit, get it wrong and
          that&apos;s an out. Most runs wins. Everyone watching can swing at every question from here.
        </p>
        <div className="row">
          {user ? (
            <Link className="btn" href="/play">
              Play along
            </Link>
          ) : (
            <a className="btn" href="/auth/patreon?next=/play">
              Sign in with Patreon
            </a>
          )}
          <Link className="btn btn-ghost" href="/standings">
            Standings
          </Link>
        </div>
      </section>

      {next && (
        <section className="card card-cream stack">
          <span className="band band-blue">{next.status === "live" ? "Live now" : "Next episode"}</span>
          <h2>
            Episode {next.number}: {next.title}
          </h2>
          <p>
            <strong>{formatAirDate(next.airs_at)}</strong>
            {next.theme ? ` · ${next.theme}` : ""}
          </p>
        </section>
      )}

      <section className="stack">
        <h2>How the game works</h2>
        <div className="hits">
          {HITS.map((h) => (
            <div key={h.label} className={`hit ${h.cls}`}>
              <b>{h.bases}</b>
              {h.label}
            </div>
          ))}
        </div>
        <p className="muted">
          Harder questions are bigger hits, and every runner advances by the hit&apos;s base value. An inning ends at three outs or eight
          pitches. Each question has a 20-second clock, on stream and here.
        </p>
      </section>

      <section className="stack">
        <div className="row between">
          <h2>What your tier gets you</h2>
          <a className="btn btn-blue btn-sm" href={env.patreonJoinUrl()} target="_blank" rel="noreferrer">
            Join on Patreon
          </a>
        </div>
        <div className="grid">
          {([0, 1, 2, 3] as Tier[]).map((t) => (
            <div key={t} className={`card tier${myTier === t ? " current" : ""}`}>
              <h3>{TIER_NAME[t]}</h3>
              <div className="price">{TIER_PRICE[t]}</div>
              <ul>
                {BENEFITS[t].map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
              {myTier === t && <p className="light" style={{ marginTop: 14 }}>Your tier</p>}
            </div>
          ))}
        </div>
      </section>

      <section className="stack">
        <h2>Hot Stove League schedule</h2>
        <div className="card">
          {episodes.map((e) => (
            <div key={e.id} className="episode">
              <span className="num">{e.number}</span>
              <span className="title">{e.title}</span>
              <span className="muted small">
                {formatAirDate(e.airs_at)}
                {e.status === "done" ? " · Final" : ""}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
