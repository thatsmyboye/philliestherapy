import { NextResponse, type NextRequest } from "next/server";
import { env } from "@/lib/env";
import { ingest, type IngestPayload } from "@/lib/live";
import { safeEqual } from "@/lib/secure";

/**
 * The overlay on the streaming PC posts here whenever the question, clock,
 * reveal or standings change. Authenticated by a shared secret; the overlay is
 * never reachable from the internet, it only calls out.
 */
export async function POST(req: NextRequest) {
  const secret = env.ingestSecret();
  const auth = req.headers.get("authorization") ?? "";
  if (!secret || !auth.startsWith("Bearer ") || !safeEqual(auth.slice(7), secret)) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }
  let payload: IngestPayload;
  try {
    payload = (await req.json()) as IngestPayload;
  } catch {
    return NextResponse.json({ ok: false, error: "bad json" }, { status: 400 });
  }
  try {
    const awards = await ingest(payload);
    return NextResponse.json({ ok: true, awards });
  } catch (err) {
    console.error("Ingest failed:", err);
    return NextResponse.json({ ok: false, error: "ingest failed" }, { status: 500 });
  }
}
