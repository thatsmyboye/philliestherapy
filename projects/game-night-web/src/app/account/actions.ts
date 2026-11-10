"use server";

import { redirect } from "next/navigation";
import { getCurrentUser, refreshTier } from "@/lib/users";

export async function recheckTier(): Promise<void> {
  const user = await getCurrentUser();
  if (!user) redirect("/?error=signed_out");
  const updated = await refreshTier(user);
  // refreshTier leaves the user untouched when Patreon can't be reached.
  redirect(updated.tier_checked_at === user.tier_checked_at ? "/account?error=refresh_failed" : "/account?notice=tier_refreshed");
}
