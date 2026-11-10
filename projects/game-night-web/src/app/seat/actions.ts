"use server";

import { redirect } from "next/navigation";
import { requireDb } from "@/lib/db";
import { env } from "@/lib/env";
import { discordReady, effectiveTier, getCurrentUser } from "@/lib/users";

export async function claimSeat(formData: FormData): Promise<void> {
  const user = await getCurrentUser({ fresh: true });
  if (!user) redirect("/?error=signed_out");
  if (effectiveTier(user) < 3 || !discordReady(user)) redirect("/seat?error=seat_tier");

  const episodeId = Number(formData.get("episode_id"));
  const { data, error } = await requireDb().rpc("gn_claim_seat", { p_user: user.id, p_episode: episodeId });
  if (error) throw new Error(`Seat claim failed: ${error.message}`);
  if (data === "ok") redirect("/seat?notice=seat_claimed");
  redirect(`/seat?error=seat_${data === "full" || data === "already" ? data : "closed"}`);
}

export async function releaseSeat(): Promise<void> {
  const user = await getCurrentUser();
  if (!user) redirect("/?error=signed_out");
  const client = requireDb();
  const { data: claim } = await client
    .from("gn_seat_claims")
    .select("id, gn_episodes(status)")
    .eq("user_id", user.id)
    .eq("season", env.season())
    .maybeSingle();
  const ep = claim?.gn_episodes as { status: string } | { status: string }[] | null | undefined;
  const status = Array.isArray(ep) ? ep[0]?.status : ep?.status;
  // Once the episode is live or done the seat has been used.
  if (claim && status === "upcoming") await client.from("gn_seat_claims").delete().eq("id", claim.id);
  redirect("/seat?notice=seat_released");
}
