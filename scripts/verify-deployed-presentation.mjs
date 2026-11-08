#!/usr/bin/env node
/**
 * G5: deployed presentation interactions and analytics validation.
 *
 * Usage: node scripts/verify-deployed-presentation.mjs [url]
 *        (defaults to DEPLOYED_URL env var)
 *
 * Fetches the live page and checks, over plain HTTP:
 *  1. The page renders the call control and headline (server-rendered HTML, no JS needed).
 *  2. The demo-mode disclosure survives deployment.
 *  3. No PII forms or tracking beyond Vercel Analytics is embedded.
 *  4. Response headers/security basics are sane.
 *
 * Note: this validates the deployed artifact. Vercel Analytics events are
 * client-side; their delivery is validated by the @vercel/analytics package
 * itself and the events' presence in the served JS (G4).
 */
const url =
  process.argv[2] || process.env.DEPLOYED_URL || process.env.VERCEL_URL || "";
const failures = [];
const ok = (cond, label) => {
  console.log(`${cond ? "  ✓" : "  ✗"} ${label}`);
  if (!cond) failures.push(label);
};

console.log(`G5: deployed presentation verification — ${url}`);
if (!url) {
  console.error("DEPLOYED_PRESENTATION_FAILED: no URL provided");
  process.exit(1);
}
const target = url.startsWith("http") ? url : `https://${url}`;

let res;
try {
  res = await fetch(target, { redirect: "follow" });
} catch (err) {
  console.error(`DEPLOYED_PRESENTATION_FAILED: fetch error: ${err.message}`);
  process.exit(1);
}
const html = await res.text();

ok(res.ok, `HTTP ${res.status} from ${target}`);
ok(html.includes("Talk to a voice agent."), "headline rendered");
ok(/aria-label="[^"]*call/i.test(html), "call control (aria-label containing 'call') present");
ok(html.includes("no S3, no PostgreSQL"), "demo-mode disclosure present");

const headers = res.headers;
ok(
  !headers.get("x-powered-by")?.includes("Express"),
  "no accidental backend framework exposure"
);
const ct = headers.get("content-type") || "";
ok(ct.includes("text/html"), "served as HTML");

// PII / tracking surface checks — scoped to actual form/input elements and
// tracking script tags, not arbitrary substrings inside minified JS payloads.
ok(!/<form[\s>]/i.test(html), "no form elements (nothing collects PII)");
ok(
  !/<input[^>]+(name|id)\s*=\s*["'](email|password|phone|name|address)/i.test(html),
  "no PII input fields"
);
ok(
  !/<script[^>]+src\s*=\s*["'][^"']*(googletagmanager|doubleclick|facebook)/i.test(html),
  "no third-party trackers beyond Vercel"
);
ok(!/sk-or-[a-zA-Z0-9]|AKIA[0-9A-Z]{16}/.test(html), "HTML free of embedded credentials");
// Vercel Analytics / Speed Insights load as npm packages inlined into the JS
// chunks at runtime; fetch the chunks and look for the markers.
const chunkMatches = [...html.matchAll(/src="(\/_next\/static\/[^"]+\.js)"/g)];
let js = "";
for (const [, src] of chunkMatches.slice(0, 12)) {
  try {
    js += await fetch(new URL(src, target)).then((r) => r.text());
  } catch {
    /* chunk fetch is best-effort */
  }
}
for (const event of ["presentation_started", "call_started", "call_ended", "contact_link_clicked"]) {
  ok(js.includes(event), `analytics event served: ${event}`);
}
ok(
  js.includes("https://vitals.vercel") || js.includes("va.vercel"),
  "Vercel analytics/speed-insights instrumentation served",
);

if (failures.length) {
  console.error(`DEPLOYED_PRESENTATION_FAILED (${failures.length} checks)`);
  process.exit(1);
}
console.log("DEPLOYED_PRESENTATION_PASSED");
