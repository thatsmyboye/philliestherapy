"use server";

import { redirect } from "next/navigation";
import { requireDb } from "@/lib/db";
import { easternLocalToIso } from "@/lib/time";
import { getCurrentUser, isAdmin } from "@/lib/users";

async function requireAdmin(): Promise<void> {
  const user = await getCurrentUser();
  if (!isAdmin(user)) redirect("/");
}

const STATUSES = ["upcoming", "live", "done"];

export async function saveEpisode(formData: FormData): Promise<void> {
  await requireAdmin();
  const status = String(formData.get("status"));
  const { error } = await requireDb()
    .from("gn_episodes")
    .update({
      title: String(formData.get("title") ?? "").trim().slice(0, 120) || "Untitled",
      theme: String(formData.get("theme") ?? "").trim().slice(0, 200) || null,
      airs_at: easternLocalToIso(String(formData.get("airs_at") ?? "")),
      status: STATUSES.includes(status) ? status : "upcoming",
      exec_seats: Math.max(0, Math.min(4, Number(formData.get("exec_seats")) || 0)),
    })
    .eq("id", Number(formData.get("id")));
  if (error) throw new Error(`Could not save episode: ${error.message}`);
  redirect("/admin?notice=saved");
}

export async function removeClaim(formData: FormData): Promise<void> {
  await requireAdmin();
  await requireDb().from("gn_seat_claims").delete().eq("id", String(formData.get("id")));
  redirect("/admin?notice=saved");
}
