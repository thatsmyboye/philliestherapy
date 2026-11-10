// Answer matching and Bullpen grading. Pure functions.
// `normalize` and `answerMatches` are a direct port of the overlay's matcher
// (Game Night/overlay/server.js) so web and Twitch `!swing` answers are judged alike.

export const DIFF_BASES: Record<string, number> = { Single: 1, Double: 2, Triple: 3, HR: 4 };

export function normalize(s: unknown): string {
  return String(s ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\b(the|a|an)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function answerMatches(answer: string, acceptAlso: string | null | undefined, text: string): boolean {
  const t = normalize(text);
  if (!t) return false;
  const accept = [answer, ...(acceptAlso || "").split("|")].map(normalize).filter(Boolean);
  return accept.some((a) => a === t || (a.length > 4 && t.includes(a)));
}

export interface SwingToGrade {
  id: string;
  answer: string;
  createdAt: string;
  /** Tier 1+ ($5 and up) can score Bullpen points. */
  eligible: boolean;
}

export interface GradeResult {
  correct: Map<string, boolean>;
  /** The earliest correct swing from an eligible member, if any. */
  winnerId: string | null;
}

export function gradeSwings(swings: SwingToGrade[], answer: string, acceptAlso: string | null | undefined): GradeResult {
  const correct = new Map<string, boolean>();
  let winner: SwingToGrade | null = null;
  for (const s of swings) {
    const ok = answerMatches(answer, acceptAlso, s.answer);
    correct.set(s.id, ok);
    if (ok && s.eligible && (!winner || s.createdAt < winner.createdAt)) winner = s;
  }
  return { correct, winnerId: winner?.id ?? null };
}
