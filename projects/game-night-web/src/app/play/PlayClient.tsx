"use client";

import { createClient } from "@supabase/supabase-js";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Live, PlayState } from "@/lib/live";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const MAX_ANSWER_LENGTH = 120;
const DIFF_LABEL: Record<string, string> = { Single: "Single", Double: "Double", Triple: "Triple", HR: "Home Run" };

export function PlayClient({ initial, joinUrl }: { initial: PlayState; joinUrl: string }) {
  const [state, setState] = useState(initial);
  const [connected, setConnected] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  // Server time minus this device's clock, so the countdown doesn't depend on the phone being right.
  const offset = useRef(initial.now - Date.now());

  const apply = useCallback((next: PlayState) => {
    offset.current = next.now - Date.now();
    setState(next);
  }, []);

  const refetch = useCallback(async () => {
    try {
      const res = await fetch("/api/live", { cache: "no-store" });
      if (res.status === 401 || res.status === 403) {
        window.location.reload();
        return;
      }
      if (res.ok) apply((await res.json()) as PlayState);
    } catch {
      /* offline for a moment; the next poll retries */
    }
  }, [apply]);

  // Instant updates from Supabase Realtime; the row it sends is the public live state.
  useEffect(() => {
    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return;
    const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, { auth: { persistSession: false } });
    const channel = supabase
      .channel("gn_live")
      .on("postgres_changes", { event: "*", schema: "public", table: "gn_live" }, (payload) => {
        const row = payload.new as Partial<Live> | null;
        if (row && row.status) setState((s) => ({ ...s, live: { ...s.live, ...row }, mySwing: row.question_id === s.live.question_id ? s.mySwing : null }));
        void refetch();
      })
      .subscribe((status) => setConnected(status === "SUBSCRIBED"));
    return () => {
      void supabase.removeChannel(channel);
    };
  }, [refetch]);

  // Polling: the safety net when Realtime is connected, the main path when it isn't.
  useEffect(() => {
    const every = connected ? 15_000 : 3_000;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void refetch();
    }, every);
    const onVisible = () => document.visibilityState === "visible" && void refetch();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [connected, refetch]);

  const { live, mySwing } = state;
  const questionId = live.question_id;

  useEffect(() => {
    setAnswer("");
    setProblem(null);
  }, [questionId]);

  useEffect(() => {
    if (live.status !== "open") return;
    const id = setInterval(() => setTick((t) => t + 1), 100);
    return () => clearInterval(id);
  }, [live.status, questionId]);

  void tick;
  const total = live.opens_at && live.closes_at ? Math.max(1, Date.parse(live.closes_at) - Date.parse(live.opens_at)) : 20_000;
  const remaining = live.closes_at ? Math.max(0, Date.parse(live.closes_at) - (Date.now() + offset.current)) : 0;
  const open = live.status === "open" && remaining > 0;
  const seconds = Math.ceil(remaining / 1000);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!answer.trim() || sending) return;
    setSending(true);
    setProblem(null);
    try {
      const res = await fetch("/api/swing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer }),
      });
      const json = (await res.json()) as { result?: string; state?: PlayState; error?: string };
      if (json.state) apply(json.state);
      if (json.result === "closed") setProblem("Time ran out before that answer arrived.");
      else if (!res.ok && json.result !== "already") setProblem("That didn't go through. Try again.");
    } catch {
      setProblem("That didn't go through. Check your connection and try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="stack">
      <div className="row between">
        <div>
          <p className="light">The Bullpen{live.episode_number ? ` · Episode ${live.episode_number}` : ""}</p>
          <h1 style={{ fontSize: "clamp(1.8rem, 6vw, 3rem)" }}>Play along</h1>
        </div>
        <p className="small muted" role="status">
          <span className={`dot${connected ? " on" : ""}`} />
          {connected ? "Live" : "Connecting"}
        </p>
      </div>

      <div className="play">
        <section aria-live="polite">
          {live.status === "idle" || !live.question ? (
            <div className="pitch pitch-wait">
              <h2>Waiting for the next pitch</h2>
              <p className="muted">Keep this page open. The question appears here the moment it&apos;s shown on stream.</p>
            </div>
          ) : (
            <div className="pitch">
              <div className="pitch-top">
                <div className="pitch-tags">
                  {live.category && <span className="badge">{live.category}</span>}
                  {live.difficulty && <span className={`badge diff-${live.difficulty}`}>{DIFF_LABEL[live.difficulty] ?? live.difficulty}</span>}
                </div>
                {open && (
                  <div className={`clock${seconds <= 5 ? " low" : ""}`} role="timer" aria-label={`${seconds} seconds left`}>
                    <svg viewBox="0 0 64 64" aria-hidden="true">
                      <circle className="track" cx="32" cy="32" r="27" />
                      <circle className="arc" cx="32" cy="32" r="27" strokeDasharray={169.6} strokeDashoffset={169.6 * (1 - Math.min(1, remaining / total))} />
                    </svg>
                    <span>{seconds}</span>
                  </div>
                )}
              </div>

              <p className="q">{live.question}</p>

              {live.status === "revealed" && live.answer && (
                <div className="answer-bar">
                  <span className="small">Answer</span>
                  <b>{live.answer}</b>
                </div>
              )}

              {mySwing ? (
                <div className="locked">
                  <span className="small muted">Your final answer</span>
                  <b>{mySwing.answer}</b>
                  {mySwing.correct === null ? (
                    <p className="small muted">Locked in. Results come with the answer on stream.</p>
                  ) : mySwing.correct ? (
                    <p className="verdict good">
                      Correct{mySwing.points > 0 ? ` · +${mySwing.points} Bullpen ${mySwing.points === 1 ? "point" : "points"}` : ""}
                    </p>
                  ) : (
                    <p className="verdict bad">Out</p>
                  )}
                </div>
              ) : open ? (
                <form className="stack" onSubmit={submit}>
                  <label>
                    Your answer (one swing, no changes)
                    <input
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      maxLength={MAX_ANSWER_LENGTH}
                      autoComplete="off"
                      autoCapitalize="off"
                      autoFocus
                      enterKeyHint="send"
                    />
                  </label>
                  <button className="btn" disabled={sending || !answer.trim()}>
                    {sending ? "Sending" : "Swing"}
                  </button>
                </form>
              ) : (
                <p className="muted">{live.status === "revealed" ? "You didn't swing at this one." : "Time. Waiting for the answer on stream."}</p>
              )}

              {problem && (
                <p className="small" role="alert" style={{ color: "var(--red)" }}>
                  {problem}
                </p>
              )}

              {live.status === "revealed" && live.first_correct && (
                <p className="small muted">
                  First correct in the Bullpen: <strong>{live.first_correct}</strong>
                </p>
              )}
            </div>
          )}
        </section>

        <aside className="card stack">
          <div className="row between">
            <h3>Bullpen leaders</h3>
            <span className="badge">You: {state.myPoints}</span>
          </div>
          {state.leaderboard.length === 0 ? (
            <p className="muted small">No points yet tonight. The first correct answer to each question scores its base value.</p>
          ) : (
            <div>
              {state.leaderboard.map((r, i) => (
                <div key={r.name} className="leader-row">
                  <span className="who">
                    <i>{i + 1}</i>
                    <span>{r.name}</span>
                  </span>
                  <b>{r.points}</b>
                </div>
              ))}
            </div>
          )}
          {!state.eligible && (
            <p className="small muted">
              You can swing at every question on the free tier. Bullpen points and the leaderboard are for members at $5 and up.{" "}
              <a href={joinUrl} target="_blank" rel="noreferrer">
                Join on Patreon
              </a>
              .
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
