/** Browser side of the funnel: posts to our own /api/track, which adds geo and a daily visitor hash. */

export type TrackType = "page_view" | "call_started" | "call_completed" | "report_shared" | "report_opened";
export type ShareChannel = "x" | "linkedin" | "whatsapp" | "copy" | "native";

const UTM_KEYS = ["source", "medium", "campaign", "content"] as const;

export function trackEvent(type: TrackType, extra: { share_id?: string; channel?: ShareChannel } = {}) {
  if (typeof window === "undefined") return;
  try {
    const params = new URLSearchParams(location.search);
    const utm: Record<string, string> = {};
    for (const k of UTM_KEYS) {
      const v = params.get(`utm_${k}`);
      if (v) utm[k] = v.slice(0, 100);
    }
    let referrer_host: string | undefined;
    try {
      const host = document.referrer ? new URL(document.referrer).host : "";
      if (host && host !== location.host) referrer_host = host;
    } catch {
      // Malformed referrer: leave it out.
    }
    const body = JSON.stringify({
      type,
      path: location.pathname,
      ...extra,
      utm: Object.keys(utm).length ? utm : undefined,
      referrer_host,
    });
    const sent = navigator.sendBeacon?.("/api/track", new Blob([body], { type: "application/json" }));
    if (!sent) {
      void fetch("/api/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    }
  } catch {
    // Tracking never breaks the page.
  }
}
