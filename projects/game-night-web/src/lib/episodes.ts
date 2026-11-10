import { db } from "./db";
import { env } from "./env";

export interface Episode {
  id: number;
  season: string;
  number: number;
  title: string;
  theme: string | null;
  airs_at: string | null;
  status: "upcoming" | "live" | "done";
  exec_seats: number;
}

export interface StandingRow {
  name: string;
  wins: number;
  runs: number;
  potg: number;
  points: number;
}

// Shown before the database is connected, so the public pages still tell the story.
const FALLBACK: Episode[] = [
  { number: 1, title: "Hot Stove Premiere", theme: "Winter Meetings week" },
  { number: 2, title: "Hall of Fame Week", theme: "Franchise History and Postseason" },
  { number: 3, title: "Spring Training Preview", theme: "Around the League and Connections" },
  { number: 4, title: "Championship", theme: "Top three from Episodes 1-3. Opening Day eve." },
].map((e) => ({ ...e, id: e.number, season: "2026-27", airs_at: null, status: "upcoming" as const, exec_seats: e.number < 4 ? 1 : 0 }));

export async function listEpisodes(): Promise<Episode[]> {
  const client = db();
  if (!client) return FALLBACK;
  const { data } = await client.from("gn_episodes").select("*").eq("season", env.season()).order("number");
  return (data as Episode[] | null) ?? [];
}

/** The live episode if there is one, otherwise the next upcoming one. */
export function pickNextEpisode(episodes: Episode[]): Episode | null {
  return episodes.find((e) => e.status === "live") ?? episodes.find((e) => e.status === "upcoming") ?? null;
}

export async function listStandings(): Promise<StandingRow[]> {
  const client = db();
  if (!client) return [];
  const { data } = await client
    .from("gn_standings")
    .select("name, wins, runs, potg, points")
    .eq("season", env.season())
    .order("points", { ascending: false })
    .order("runs", { ascending: false });
  return (data as StandingRow[] | null) ?? [];
}

export function formatAirDate(iso: string | null): string {
  if (!iso) return "Date to be announced";
  return new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  }).format(new Date(iso));
}
