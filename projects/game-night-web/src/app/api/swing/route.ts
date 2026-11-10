import { NextResponse, type NextRequest } from "next/server";
import { env } from "@/lib/env";
import { getPlayState, submitSwing } from "@/lib/live";
import { discordReady, getCurrentUser } from "@/lib/users";

export async function POST(req: NextRequest) {
  // The session cookie is SameSite=Lax; also require a same-origin request.
  const origin = req.headers.get("origin");
  if (origin && origin !== env.appUrl() && origin !== req.nextUrl.origin) {
    return NextResponse.json({ error: "bad_origin" }, { status: 403 });
  }
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "signed_out" }, { status: 401 });
  if (!discordReady(user)) return NextResponse.json({ error: "discord_required" }, { status: 403 });

  let answer = "";
  try {
    answer = String(((await req.json()) as { answer?: unknown }).answer ?? "");
  } catch {
    return NextResponse.json({ error: "bad_json" }, { status: 400 });
  }
  const result = await submitSwing(user, answer);
  return NextResponse.json({ result, state: await getPlayState(user) }, { status: result === "ok" || result === "already" ? 200 : 409 });
}
