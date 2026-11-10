import { NextResponse } from "next/server";
import { env } from "@/lib/env";
import { clearSession } from "@/lib/session";

// POST only, so a link or image on another site can't sign someone out.
export async function POST() {
  await clearSession();
  return NextResponse.redirect(`${env.appUrl()}/`, 303);
}
