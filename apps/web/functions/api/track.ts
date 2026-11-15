/**
 * Cloudflare Pages Function: the analytics edge for the static site.
 *
 * Ports the former Next.js route handler (apps/web/src/app/api/track/route.ts, removed when
 * the site became a static export). Validates the event, hashes the client IP daily with the
 * shared secret (Web Crypto, no Node compat needed), and forwards to the control Lambda with
 * the secret. Responds 204 first in spirit: the forward runs in waitUntil and its failures are
 * ignored — analytics must never affect the visitor.
 */

const TYPES = new Set(["page_view", "call_started", "call_completed", "report_shared", "report_opened"]);
const CHANNELS = new Set(["x", "linkedin", "whatsapp", "copy", "native"]);
const SHARE_ID = /^[0-9a-f]{32}$/;
const HOST = /^[a-z0-9.-]+(:\d+)?$/i;

const clip = (v: unknown, n: number) => (typeof v === "string" ? v.trim().slice(0, n) : undefined);
const empty = () => new Response(null, { status: 204 });

async function sha256(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Minimal Pages Function context (avoids a workers-types dependency in the Next app). */
interface PagesContext<Env> {
  request: Request;
  env: Env;
  waitUntil: (promise: Promise<unknown>) => void;
}

interface TrackEnv {
  TRACK_SECRET?: string;
  NEXT_PUBLIC_DEMO_CONTROL_URL?: string;
}

export const onRequestPost = async ({ request, env, waitUntil }: PagesContext<TrackEnv>) => {
  const control = env.NEXT_PUBLIC_DEMO_CONTROL_URL?.replace(/\/+$/, "");
  const secret = env.TRACK_SECRET;
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

  // Sessionless analytics: never store the raw IP, only a daily hash with the secret.
  const ip = request.headers.get("cf-connecting-ip") ?? "";
  const day = new Date().toISOString().slice(0, 10);
  const visitor = ip ? await sha256(ip + day + secret) : undefined;

  const decode = (v: string | null) => {
    if (!v) return undefined;
    try {
      return decodeURIComponent(v);
    } catch {
      return v;
    }
  };
  // The control API requires lat/lon in geo (Vercel-only request headers). Cloudflare provides
  // country/region/city only, so geo is omitted here rather than sending a row the API rejects.
  const geo = undefined;
  void decode;

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

  waitUntil(
    fetch(`${control}/track`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Track-Secret": secret },
      body: payload,
      signal: AbortSignal.timeout(4000),
    }).catch(() => {
      // Dropped event: analytics must not affect the visitor.
    }),
  );
  return empty();
};
