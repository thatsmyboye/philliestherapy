import { NextResponse, type NextRequest } from "next/server";
import { discordAuthorizeUrl } from "@/lib/discord";
import { env } from "@/lib/env";
import { readSessionUserId, startOAuthState } from "@/lib/session";

export async function GET(req: NextRequest) {
  // Discord is a link on top of a Patreon sign-in, never a login by itself.
  if (!(await readSessionUserId())) return NextResponse.redirect(`${env.appUrl()}/auth/patreon?next=/account`);
  const state = await startOAuthState("discord", req.nextUrl.searchParams.get("next"));
  return NextResponse.redirect(discordAuthorizeUrl(state));
}
