import { db, requireDb } from "./db";
import { env } from "./env";
import { DIFF_BASES, gradeSwings } from "./match";
import type { StandingRow } from "./episodes";
import { effectiveTier, type User } from "./users";

export type LiveStatus = "idle" | "open" | "closed" | "revealed";

export interface Live {
  status: LiveStatus;
  episode_number: number | null;
  episode_title: string | null;
  question_id: string | null;
  category: string | null;
  difficulty: string | null;
  question: string | null;
  answer: string | null;
  opens_at: string | null;
  closes_at: string | null;
  first_correct: string | null;
}

const IDLE: Live = {
  status: "idle",
  episode_number: null,
  episode_title: null,
  question_id: null,
  category: null,
  difficulty: null,
  question: null,
  answer: null,
  opens_at: null,
  closes_at: null,
  first_correct: null,
};

const LIVE_COLUMNS =
  "status, episode_number, episode_title, question_id, category, difficulty, question, answer, opens_at, closes_at, first_correct";

export async function getLive(): Promise<Live> {
  const client = db();
  if (!client) return IDLE;
  const { data } = await client.from("gn_live").select(LIVE_COLUMNS).eq("id", 1).maybeSingle();
  return (data as Live | null) ?? IDLE;
}

// ---------------------------------------------------------------------------
// Overlay → web (POST /api/ingest)
// ---------------------------------------------------------------------------

export interface IngestPayload {
  episode?: { number?: number; title?: string };
  /** What the overlay is showing. The answer is only sent once it is revealed on stream. */
  question?: { id: string; category?: string; difficulty?: string; text: string } | null;
  clock?: { running?: boolean; remainingMs?: number };
  revealed?: boolean;
  answer?: string;
  acceptAlso?: string;
  standings?: StandingRow[];
}

export interface Award {
  user: string;
  points: number;
}

export async function ingest(p: IngestPayload): Promise<Award[]> {
  const client = requireDb();
  const prev = await getLive();
  const now = new Date();
  const episodeNumber = Number(p.episode?.number) || prev.episode_number || 1;
  const episodeTitle = p.episode?.title ?? prev.episode_title;
  let awards: Award[] = [];
  let next: Live;

  const q = p.question;
  if (!q || !q.id || !q.text) {
    next = { ...IDLE, episode_number: episodeNumber, episode_title: episodeTitle };
  } else {
    const same = prev.question_id === q.id && prev.episode_number === episodeNumber;
    const base = {
      episode_number: episodeNumber,
      episode_title: episodeTitle,
      question_id: q.id,
      category: q.category ?? null,
      difficulty: q.difficulty ?? null,
      question: q.text,
      opens_at: same && prev.opens_at ? prev.opens_at : now.toISOString(),
    };
    if (p.revealed && typeof p.answer === "string") {
      const winner = await grade(episodeNumber, q.id, p.answer, p.acceptAlso, q.difficulty);
      if (winner) awards = [winner];
      next = {
        ...base,
        status: "revealed",
        answer: p.answer,
        closes_at: same ? prev.closes_at : now.toISOString(),
        first_correct: winner?.user ?? (same ? prev.first_correct : null),
      };
    } else {
      const remaining = Math.max(0, Number(p.clock?.remainingMs) || 0);
      const open = !!p.clock?.running && remaining > 0;
      next = {
        ...base,
        status: open ? "open" : "closed",
        answer: null,
        closes_at: open ? new Date(now.getTime() + remaining).toISOString() : same && prev.closes_at ? prev.closes_at : now.toISOString(),
        first_correct: null,
      };
    }
  }

  const { error } = await client.from("gn_live").upsert({ id: 1, ...next, updated_at: now.toISOString() });
  if (error) throw new Error(`Could not update live state: ${error.message}`);

  if (Array.isArray(p.standings)) await replaceStandings(p.standings);
  return awards;
}

type SwingRow = {
  id: string;
  answer: string;
  created_at: string;
  correct: boolean | null;
  points: number;
  gn_users: { tier: number; display_name: string | null; discord_user_id: string | null } | { tier: number; display_name: string | null; discord_user_id: string | null }[] | null;
};

function owner(row: SwingRow) {
  return Array.isArray(row.gn_users) ? row.gn_users[0] ?? null : row.gn_users;
}

/**
 * Grade every answer for a question once the host reveals it. The earliest correct
 * answer from a $5+ member earns the question's base value. Safe to call repeatedly:
 * a question is only ever awarded once.
 */
async function grade(
  episodeNumber: number,
  questionId: string,
  answer: string,
  acceptAlso: string | undefined,
  difficulty: string | undefined
): Promise<Award | null> {
  const client = requireDb();
  const { data, error } = await client
    .from("gn_swings")
    .select("id, answer, created_at, correct, points, gn_users(tier, display_name, discord_user_id)")
    .eq("season", env.season())
    .eq("episode_number", episodeNumber)
    .eq("question_id", questionId);
  if (error) throw new Error(`Could not load answers: ${error.message}`);
  const rows = (data ?? []) as unknown as SwingRow[];
  if (!rows.some((r) => r.correct === null)) return null;

  const admins = env.adminDiscordIds();
  const result = gradeSwings(
    rows.map((r) => {
      const u = owner(r);
      const isAdmin = !!u?.discord_user_id && admins.includes(u.discord_user_id);
      return { id: r.id, answer: r.answer, createdAt: r.created_at, eligible: (u?.tier ?? 0) >= 1 || isAdmin };
    }),
    answer,
    acceptAlso
  );

  const right = rows.filter((r) => result.correct.get(r.id)).map((r) => r.id);
  const wrong = rows.filter((r) => !result.correct.get(r.id)).map((r) => r.id);
  if (right.length) await client.from("gn_swings").update({ correct: true }).in("id", right);
  if (wrong.length) await client.from("gn_swings").update({ correct: false }).in("id", wrong);

  const alreadyAwarded = rows.some((r) => r.points > 0);
  if (alreadyAwarded || !result.winnerId) return null;
  const points = DIFF_BASES[difficulty ?? ""] ?? 1;
  await client.from("gn_swings").update({ points }).eq("id", result.winnerId);
  const winner = rows.find((r) => r.id === result.winnerId)!;
  return { user: owner(winner)?.display_name || "Member", points };
}

async function replaceStandings(rows: StandingRow[]): Promise<void> {
  const client = requireDb();
  const season = env.season();
  const clean = rows
    .filter((r) => r && typeof r.name === "string" && r.name.trim())
    .map((r) => ({
      season,
      name: r.name.trim().slice(0, 80),
      wins: Number(r.wins) || 0,
      runs: Number(r.runs) || 0,
      potg: Number(r.potg) || 0,
      points: Number(r.points) || 0,
      updated_at: new Date().toISOString(),
    }));
  const { data: existing } = await client.from("gn_standings").select("name").eq("season", season);
  const keep = new Set(clean.map((r) => r.name));
  const stale = (existing ?? []).map((r) => r.name as string).filter((n) => !keep.has(n));
  if (clean.length) await client.from("gn_standings").upsert(clean);
  if (stale.length) await client.from("gn_standings").delete().eq("season", season).in("name", stale);
}

// ---------------------------------------------------------------------------
// Players
// ---------------------------------------------------------------------------

export const MAX_ANSWER_LENGTH = 120;

export type SwingResult = "ok" | "closed" | "already" | "empty";

export async function submitSwing(user: User, rawAnswer: string): Promise<SwingResult> {
  const answer = rawAnswer.replace(/\s+/g, " ").trim().slice(0, MAX_ANSWER_LENGTH);
  if (!answer) return "empty";
  const live = await getLive();
  if (live.status !== "open" || !live.question_id || !live.closes_at || live.episode_number === null) return "closed";
  if (Date.now() > Date.parse(live.closes_at)) return "closed";
  const { error } = await requireDb().from("gn_swings").insert({
    user_id: user.id,
    season: env.season(),
    episode_number: live.episode_number,
    question_id: live.question_id,
    answer,
  });
  if (error) {
    if (error.code === "23505") return "already";
    throw new Error(`Could not save answer: ${error.message}`);
  }
  return "ok";
}

export interface LeaderRow {
  name: string;
  points: number;
}

export interface PlayState {
  now: number;
  live: Live;
  mySwing: { answer: string; correct: boolean | null; points: number } | null;
  myPoints: number;
  eligible: boolean;
  leaderboard: LeaderRow[];
}

export async function getPlayState(user: User): Promise<PlayState> {
  const client = requireDb();
  const live = await getLive();
  const season = env.season();
  const episode = live.episode_number;

  let mySwing: PlayState["mySwing"] = null;
  let myPoints = 0;
  let leaderboard: LeaderRow[] = [];

  if (episode !== null) {
    const [mine, scored] = await Promise.all([
      client.from("gn_swings").select("question_id, answer, correct, points").eq("season", season).eq("episode_number", episode).eq("user_id", user.id),
      client.from("gn_swings").select("points, gn_users(display_name)").eq("season", season).eq("episode_number", episode).gt("points", 0),
    ]);
    for (const row of mine.data ?? []) {
      myPoints += row.points as number;
      if (row.question_id === live.question_id) {
        mySwing = { answer: row.answer as string, correct: row.correct as boolean | null, points: row.points as number };
      }
    }
    const totals = new Map<string, number>();
    for (const row of (scored.data ?? []) as unknown as { points: number; gn_users: { display_name: string | null } | { display_name: string | null }[] | null }[]) {
      const u = Array.isArray(row.gn_users) ? row.gn_users[0] : row.gn_users;
      const name = u?.display_name || "Member";
      totals.set(name, (totals.get(name) ?? 0) + row.points);
    }
    leaderboard = [...totals].map(([name, points]) => ({ name, points })).sort((a, b) => b.points - a.points).slice(0, 10);
  }

  return { now: Date.now(), live, mySwing, myPoints, eligible: effectiveTier(user) >= 1, leaderboard };
}
