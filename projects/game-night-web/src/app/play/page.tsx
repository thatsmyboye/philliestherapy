import type { Metadata } from "next";
import { AccessGate, needsGate } from "@/components/Gate";
import { env } from "@/lib/env";
import { getPlayState } from "@/lib/live";
import { getCurrentUser } from "@/lib/users";
import { PlayClient } from "./PlayClient";

export const metadata: Metadata = { title: "Play along" };
export const dynamic = "force-dynamic";

export default async function Play() {
  const user = await getCurrentUser({ fresh: true });
  if (needsGate(user) || !user) {
    return (
      <div className="stack">
        <p className="light">The Bullpen</p>
        <h1 style={{ fontSize: "clamp(2rem, 7vw, 3.5rem)" }}>Play along</h1>
        <AccessGate user={user} next="/play" what="play along" />
      </div>
    );
  }
  const initial = await getPlayState(user);
  return <PlayClient initial={initial} joinUrl={env.patreonJoinUrl()} />;
}
