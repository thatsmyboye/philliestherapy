import { NextResponse, type NextRequest } from "next/server";
import { exchangeDiscordCode, fetchDiscordProfile } from "@/lib/discord";
import { env } from "@/lib/env";
import { finishOAuthState, readSessionUserId } from "@/lib/session";
import { linkDiscord } from "@/lib/users";

function back(path: string) {
  return NextResponse.redirect(`${env.appUrl()}${path}`);
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const next = await finishOAuthState("discord", params.get("state"));
  const code = params.get("code");
  const userId = await readSessionUserId();
  if (!userId) return back("/?error=signed_out");
  if (params.get("error")) return back("/account?error=discord_denied");
  if (!next || !code) return back("/account?error=discord_state");

  try {
    const profile = await fetchDiscordProfile(await exchangeDiscordCode(code));
    if ((await linkDiscord(userId, profile)) === "taken") return back("/account?error=discord_taken");
    if (!profile.inGuild) return back("/account?notice=join_server");
  } catch (err) {
    console.error("Discord link failed:", err);
    return back("/account?error=discord_failed");
  }
  return back(next);
}
