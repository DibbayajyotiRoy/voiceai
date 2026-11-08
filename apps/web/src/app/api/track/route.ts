import { createHash } from "node:crypto";
import { after } from "next/server";

// Event types and channels the browser may send; anything else is dropped.
const TYPES = new Set(["page_view", "call_started", "call_completed", "report_shared", "report_opened"]);
const CHANNELS = new Set(["x", "linkedin", "whatsapp", "copy", "native"]);
const SHARE_ID = /^[0-9a-f]{32}$/;
const HOST = /^[a-z0-9.-]+(:\d+)?$/i;

const clip = (v: unknown, n: number) => (typeof v === "string" ? v.trim().slice(0, n) : undefined);
const empty = () => new Response(null, { status: 204 });

/** Sessionless analytics. Never forwards or logs the raw IP: only a daily hash of it leaves here. */
export async function POST(request: Request) {
  const control = process.env.NEXT_PUBLIC_DEMO_CONTROL_URL?.replace(/\/+$/, "");
  const secret = process.env.TRACK_SECRET;
  if (!control || !secret) return empty();

  const b = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!b || typeof b !== "object") return empty();
  if (typeof b.type !== "string" || !TYPES.has(b.type)) return empty();
  const path = clip(b.path, 200);
  if (!path || !path.startsWith("/")) return empty();

  const shareId = typeof b.share_id === "string" && SHARE_ID.test(b.share_id) ? b.share_id : undefined;
  const channel = typeof b.channel === "string" && CHANNELS.has(b.channel) ? b.channel : undefined;

  let utm: Record<string, string> | undefined;
  if (b.utm && typeof b.utm === "object") {
    const u = b.utm as Record<string, unknown>;
    utm = {};
    for (const k of ["source", "medium", "campaign", "content"]) {
      const v = clip(u[k], 100);
      if (v) utm[k] = v;
    }
    if (!Object.keys(utm).length) utm = undefined;
  }
  const refHost = clip(b.referrer_host, 200);
  const referrer_host = refHost && HOST.test(refHost) ? refHost : undefined;

  const h = request.headers;
  const ip = h.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "";
  const day = new Date().toISOString().slice(0, 10);
  const visitor = ip ? createHash("sha256").update(ip + day + secret).digest("hex") : undefined;

  const decode = (v: string | null) => {
    if (!v) return undefined;
    try {
      return decodeURIComponent(v);
    } catch {
      return v;
    }
  };
  const country = h.get("x-vercel-ip-country") ?? undefined;
  const num = (v: string | null) => (v && Number.isFinite(Number(v)) ? Number(v) : undefined);
  const geo = country
    ? {
        country,
        region: decode(h.get("x-vercel-ip-country-region")),
        city: decode(h.get("x-vercel-ip-city")),
        lat: num(h.get("x-vercel-ip-latitude")),
        lon: num(h.get("x-vercel-ip-longitude")),
      }
    : undefined;

  const payload = JSON.stringify({
    type: b.type,
    path,
    share_id: shareId,
    channel,
    utm,
    referrer_host,
    geo,
    visitor,
  });

  // Respond 204 first; the forward runs after the response and its failures are ignored.
  after(async () => {
    try {
      await fetch(`${control}/track`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Track-Secret": secret },
        body: payload,
        signal: AbortSignal.timeout(4000),
      });
    } catch {
      // Dropped event: analytics must not affect the visitor.
    }
  });
  return empty();
}
