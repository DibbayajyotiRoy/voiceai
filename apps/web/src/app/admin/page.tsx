"use client";

import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import {
  fmtDateTime,
  fmtDuration,
  fmtMs,
  fmtSec,
  fmtUsd,
  type AdminSummary,
} from "@/lib/report";

const CONTROL_URL = process.env.NEXT_PUBLIC_DEMO_CONTROL_URL?.replace(/\/+$/, "");
const TOKEN_KEY = "voiceai-admin-token";
const REFRESH_MS = 60_000;

// sessionStorage only: the token dies with the tab and never reaches localStorage.
const readToken = () => {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // storage blocked: the gate simply asks again
  }
};
const writeToken = (t: string | null) => {
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, t);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage blocked: nothing to clear
  }
};

export default function AdminPage() {
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [data, setData] = useState<AdminSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (t: string) => {
    if (!CONTROL_URL) {
      setError("The control URL is not set in this build.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${CONTROL_URL}/admin/summary`, {
        headers: { Authorization: `Bearer ${t}` },
        cache: "no-store",
      });
      if (res.status === 401) {
        writeToken(null);
        setToken(null);
        setData(null);
        setError("That token was not accepted. Enter it again.");
        return;
      }
      if (!res.ok) throw new Error(`Control API returned HTTP ${res.status}.`);
      setData(await res.json());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the control API.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Read the stored token once on mount (client only), then load and refresh while visible.
  useEffect(() => {
    // Syncing from sessionStorage (an external store) on mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(readToken());
    setReady(true);
  }, []);

  useEffect(() => {
    if (!token) return;
    // Syncing with the control API: the fetch's state updates are the point of the effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(token);
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(token);
    }, REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void load(token);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [token, load]);

  const unlock = () => {
    const t = draft.trim();
    if (!t) return;
    writeToken(t);
    setDraft("");
    setError("");
    setToken(t);
  };

  const signOut = () => {
    writeToken(null);
    setToken(null);
    setData(null);
    setError("");
    setDraft("");
  };

  if (!ready) {
    return <main id="main" className="wrap min-h-svh py-8" />;
  }

  if (!token) {
    return (
      <main id="main" className="wrap flex min-h-svh flex-col justify-center gap-8 py-16">
        <p className="phase">
          <b>admin</b> restricted
        </p>
        <h1 className="text-[length:var(--t-l)] font-semibold tracking-tight">Admin</h1>
        <div className="w-full max-w-sm space-y-3">
          <label htmlFor="admin-token" className="block text-sm text-muted">
            Admin token
          </label>
          <input
            id="admin-token"
            type="password"
            autoComplete="off"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
              if (e.key === "Enter") unlock();
            }}
            className="mono w-full border border-line bg-transparent px-3 py-3 text-ink"
          />
          <button type="button" onClick={unlock} className="key key--solid">
            Unlock
          </button>
        </div>
        {error && (
          <p role="alert" className="mono text-sm text-muted">
            {error}
          </p>
        )}
      </main>
    );
  }

  return (
    <main id="main" className="wrap flex min-h-svh flex-col gap-10 py-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-2">
          <p className="text-lg font-semibold tracking-tight">voiceai admin</p>
          <p className="mono text-sm text-muted">
            backend{" "}
            <span className="rounded-full border border-line px-2 py-0.5 text-ink">
              {data?.backend.state ?? "unknown"}
            </span>
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => void load(token)} disabled={loading} className="key">
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <button type="button" onClick={signOut} className="key">
            Sign out
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="mono text-sm text-muted">
          {error}
        </p>
      )}

      {data ? <Dashboard data={data} /> : <p className="text-muted">Loading…</p>}
    </main>
  );
}

function Dashboard({ data }: { data: AdminSummary }) {
  const { totals, aws_cost: aws } = data;
  const tiles: { label: string; value: string; note?: string }[] = [
    { label: "Calls", value: String(totals.calls) },
    { label: "Minutes", value: totals.minutes.toFixed(1) },
    { label: "Median reply", value: fmtSec(totals.p50_ms) },
    { label: "p95 reply", value: fmtSec(totals.p95_ms) },
    { label: "Est. model cost", value: fmtUsd(totals.est_cost_usd, "not measured") },
    {
      label: "AWS cost, month to date",
      value: fmtUsd(aws.month_to_date_usd),
      note: aws.error ? "unavailable" : "account-wide",
    },
  ];
  return (
    <>
      <section aria-label="Totals" className="grid grid-cols-2 gap-px border border-line bg-line lg:grid-cols-6">
        {tiles.map((t) => (
          <div key={t.label} className="bg-ground p-4">
            <p className="text-sm text-muted">{t.label}</p>
            <p className="figure num mono mt-2 text-2xl text-ink">{t.value}</p>
            {t.note && <p className="mt-1 text-xs text-muted">{t.note}</p>}
          </div>
        ))}
      </section>

      <section aria-labelledby="daily-title" className="space-y-3">
        <h2 id="daily-title" className="phase">
          AWS cost per day
        </h2>
        {aws.error ? (
          <p className="text-sm text-muted">AWS cost unavailable: {aws.error}</p>
        ) : (
          <DailyChart daily={aws.daily} />
        )}
      </section>

      <section aria-labelledby="service-title" className="space-y-3">
        <h2 id="service-title" className="phase">
          Cost by service, month to date
        </h2>
        {aws.by_service.length === 0 ? (
          <p className="text-sm text-muted">No service costs yet.</p>
        ) : (
          <ServiceList services={aws.by_service} />
        )}
      </section>

      <section aria-labelledby="calls-title" className="space-y-3">
        <h2 id="calls-title" className="phase">
          Recent calls
        </h2>
        {data.calls.length === 0 ? (
          <p className="text-sm text-muted">No calls yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="mono num w-full min-w-[44rem] border-collapse text-sm">
              <caption className="sr-only">Recent calls, newest first</caption>
              <thead>
                <tr className="text-left text-muted">
                  {["Started", "Duration", "Turns", "Median", "p95", "Interruptions", "Est. cost"].map((h) => (
                    <th key={h} scope="col" className="border-b border-line py-2 pr-4 font-normal">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...data.calls]
                  .sort((a, b) => b.started_at.localeCompare(a.started_at))
                  .map((c) => (
                    <tr key={c.call_id} className="border-b border-line">
                      <td className="py-2 pr-4">{fmtDateTime(c.started_at)}</td>
                      <td className="py-2 pr-4">{fmtDuration(c.duration_s)}</td>
                      <td className="py-2 pr-4">{c.turns}</td>
                      <td className="py-2 pr-4">{fmtMs(c.latency_ms?.p50)}</td>
                      <td className="py-2 pr-4">{fmtMs(c.latency_ms?.p95)}</td>
                      <td className="py-2 pr-4">{c.interruptions}</td>
                      <td className="py-2 pr-4">{fmtUsd(c.est_cost_usd, "not measured")}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function DailyChart({ daily }: { daily: AdminSummary["aws_cost"]["daily"] }) {
  const [active, setActive] = useState<number | null>(null);
  const n = daily.length;
  if (n === 0) return <p className="text-sm text-muted">No daily cost data yet.</p>;

  const W = 600;
  const H = 200;
  const BASE = 170;
  const TOP = 12;
  const slot = W / n;
  const barW = slot * 0.62;
  const max = Math.max(...daily.map((d) => d.usd), 0.0001);
  const total = daily.reduce((a, d) => a + d.usd, 0);
  const peak = daily.reduce((a, d) => (d.usd > a.usd ? d : a), daily[0]);
  const summary = `Daily AWS cost, ${n} days from ${daily[0].date} to ${daily[n - 1].date}. Total ${fmtUsd(total)}. Peak ${fmtUsd(peak.usd)} on ${peak.date}.`;
  const axis = { fontFamily: "var(--font-jetbrains), monospace", fontSize: 11, fill: "var(--muted)" };

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label={summary} className="block h-56 w-full overflow-visible">
        <line x1={0} x2={W} y1={BASE} y2={BASE} style={{ stroke: "var(--line)" }} />
        {daily.map((d, i) => {
          const h = (d.usd / max) * (BASE - TOP);
          const on = active === i;
          return (
            <g
              key={d.date}
              role="img"
              tabIndex={0}
              aria-label={`${d.date}: ${fmtUsd(d.usd)}`}
              onMouseEnter={() => setActive(i)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            >
              <rect x={i * slot} y={0} width={slot} height={H} fill="transparent" />
              <rect
                x={i * slot + (slot - barW) / 2}
                y={BASE - h}
                width={barW}
                height={Math.max(h, 0)}
                style={{ fill: on ? "var(--pen)" : "var(--muted)" }}
              />
            </g>
          );
        })}
        <text x={0} y={H - 4} style={axis}>
          {daily[0].date}
        </text>
        <text x={W} y={H - 4} textAnchor="end" style={axis}>
          {daily[n - 1].date}
        </text>
        <text x={4} y={TOP} style={axis}>
          {fmtUsd(max)}
        </text>
        <text x={4} y={BASE - 4} style={axis}>
          $0
        </text>
      </svg>
      {active !== null && (
        <div
          aria-hidden="true"
          className="mono pointer-events-none absolute -top-2 bg-ink px-2 py-1 text-xs text-ground"
          style={{ left: `${((active + 0.5) / n) * 100}%`, transform: "translate(-50%, -100%)" }}
        >
          {daily[active].date} · {fmtUsd(daily[active].usd)}
        </div>
      )}
    </div>
  );
}

function ServiceList({ services }: { services: AdminSummary["aws_cost"]["by_service"] }) {
  const sorted = [...services].sort((a, b) => b.usd - a.usd);
  const max = Math.max(sorted[0].usd, 0.0001);
  return (
    <ul className="space-y-3">
      {sorted.map((s) => (
        <li key={s.service} className="space-y-1">
          <div className="flex items-baseline justify-between gap-4 text-sm">
            <span className="text-ink">{s.service}</span>
            <span className="mono num text-ink">{fmtUsd(s.usd)}</span>
          </div>
          <div aria-hidden="true" className="h-1.5 bg-line">
            <div className="h-full bg-muted" style={{ width: `${(s.usd / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
