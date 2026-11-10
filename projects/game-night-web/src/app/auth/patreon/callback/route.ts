import { NextResponse, type NextRequest } from "next/server";
import { env } from "@/lib/env";
import { exchangePatreonCode } from "@/lib/patreon";
import { createSession, finishOAuthState } from "@/lib/session";
import { upsertFromPatreon } from "@/lib/users";

function back(path: string) {
  return NextResponse.redirect(`${env.appUrl()}${path}`);
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const next = await finishOAuthState("patreon", params.get("state"));
  const code = params.get("code");
  if (params.get("error")) return back("/?error=patreon_denied");
  if (!next || !code) return back("/?error=patreon_state");

  try {
    const tokens = await exchangePatreonCode(code);
    const userId = await upsertFromPatreon(tokens);
    await createSession(userId);
  } catch (err) {
    console.error("Patreon sign-in failed:", err);
    return back("/?error=patreon_failed");
  }
  return back(next);
}
