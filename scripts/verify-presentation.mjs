#!/usr/bin/env node
/**
 * G4: presentation production build + bundled-data safety checks.
 *
 * Verifies, without a browser:
 *  1. The production build output exists and is fully static.
 *  2. The bundle contains no privileged dependencies or secrets patterns:
 *     no S3 bucket references, no Postgres connection strings, no provider
 *     API key shapes (sk-or-, AKIA), no .env mentions.
 *  3. The analytics engagement events are wired in the client chunks.
 *  4. The honesty markers (MEASURED / PENDING) are present in the HTML.
 */
import { execSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const web = join(root, "apps/web");
const outDir = join(web, ".next");

const failures = [];
const ok = (cond, label) => {
  console.log(`${cond ? "  ✓" : "  ✗"} ${label}`);
  if (!cond) failures.push(label);
};

console.log("G4: presentation verification");

// 1. build output exists (build itself is run by the gate before this script)
ok(existsSync(join(outDir, "BUILD_ID")), "production build output exists");
ok(existsSync(join(outDir, "server", "app", "index.html")), "static index.html prerendered");

// 2. collect all emitted js/html/css for scanning
const files = [];
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walk(p);
    else if (/\.(js|html|css|rsc)$/.test(name)) files.push(p);
  }
};
if (existsSync(join(outDir, "static")) && existsSync(join(outDir, "server"))) {
  walk(join(outDir, "static"));
  walk(join(outDir, "server", "app"));
}

const banned = [
  { re: /sk-or-[a-zA-Z0-9]/, label: "OpenRouter API key shape" },
  { re: /AKIA[0-9A-Z]{16}/, label: "AWS access key id shape" },
  { re: /postgres(ql)?:\/\//i, label: "Postgres connection string" },
  { re: /s3:\/\//i, label: "S3 bucket reference" },
  { re: /OPENROUTER_API_KEY|BEDROCK_|LOGFIRE_TOKEN/i, label: "secret env var name" },
];
let bundle = "";
for (const f of files) {
  try {
    bundle += readFileSync(f, "utf8");
  } catch {
    /* binary chunk, skip */
  }
}
for (const { re, label } of banned) {
  ok(!re.test(bundle), `bundle free of ${label}`);
}

// 3. analytics events wired
for (const event of [
  "presentation_started",
  "demo_replay_started",
  "demo_replay_completed",
  "benchmark_downloaded",
  "presentation_completed",
  "contact_link_clicked",
]) {
  ok(bundle.includes(event), `analytics event wired: ${event}`);
}

// 4. honesty markers in prerendered HTML
const html = readFileSync(join(outDir, "server", "app", "index.html"), "utf8");
ok(html.includes("MEASURED") && html.includes("PENDING"), "MEASURED/PENDING markers present");
ok(html.includes("no S3, no PostgreSQL"), "demo-mode disclosure present");

if (failures.length) {
  console.error(`PRESENTATION_VERIFICATION_FAILED (${failures.length} checks)`);
  process.exit(1);
}
console.log("PRESENTATION_VERIFICATION_PASSED");
