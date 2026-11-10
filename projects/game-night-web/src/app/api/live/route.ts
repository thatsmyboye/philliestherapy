import { NextResponse } from "next/server";
import { getPlayState } from "@/lib/live";
import { discordReady, getCurrentUser } from "@/lib/users";

export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "signed_out" }, { status: 401 });
  if (!discordReady(user)) return NextResponse.json({ error: "discord_required" }, { status: 403 });
  return NextResponse.json(await getPlayState(user), { headers: { "Cache-Control": "no-store" } });
}
