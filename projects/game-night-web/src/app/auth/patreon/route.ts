import { NextResponse, type NextRequest } from "next/server";
import { patreonAuthorizeUrl } from "@/lib/patreon";
import { startOAuthState } from "@/lib/session";

export async function GET(req: NextRequest) {
  const state = await startOAuthState("patreon", req.nextUrl.searchParams.get("next"));
  return NextResponse.redirect(patreonAuthorizeUrl(state));
}
