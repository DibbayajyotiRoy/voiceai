import { useState } from "react";
import type { AdminTraffic, ShareChannel, TrafficEventType, TrafficPoint } from "./types";

// World outline: "BlankMap-Equirectangular.svg" by Wikimedia Commons contributors.
// Source: https://commons.wikimedia.org/wiki/File:BlankMap-Equirectangular.svg
// License: CC0 1.0 (public domain dedication). Local copy: public/maps/world-equirectangular.svg
const MAP_SRC = "/maps/world-equirectangular.svg";
// Equirectangular viewBox of that file: 360 x 180 (2:1).
const W = 360;
const H = 180;

const TYPES: { key: TrafficEventType; label: string; fill: string }[] = [
  { key: "page_view", label: "page view", fill: "var(--muted)" },
  { key: "call_started", label: "call started", fill: "var(--pen)" },
  { key: "call_completed", label: "call completed", fill: "var(--pen)" },
  { key: "report_shared", label: "report shared", fill: "#2dd4bf" },
  { key: "report_opened", label: "report opened", fill: "#e879c6" },
];
const TYPE_BY_KEY = Object.fromEntries(TYPES.map((t) => [t.key, t])) as Record<
  TrafficEventType,
  (typeof TYPES)[number]
>;

const CHANNELS: { key: ShareChannel; label: string }[] = [
  { key: "x", label: "X" },
  { key: "linkedin", label: "LinkedIn" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "copy", label: "Copy link" },
  { key: "native", label: "Native share" },
];

const regionNames = new Intl.DisplayNames(undefined, { type: "region" });
const regionName = (code: string) => {
  try {
    return regionNames.of(code) ?? code;
  } catch {
    return code;
  }
};

// ISO-2 code -> flag emoji from regional indicator symbols.
const flag = (code: string) =>
  /^[A-Z]{2}$/.test(code)
    ? String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65))
    : "";

const pct = (part: number, whole: number) => (whole > 0 ? `${((part / whole) * 100).toFixed(1)}%` : "—");

export function TrafficSection({ traffic }: { traffic?: AdminTraffic | null }) {
  return (
    <section aria-labelledby="traffic-title" className="space-y-6">
      <h2 id="traffic-title" className="phase">
        Traffic
      </h2>
      {traffic ? <TrafficBody traffic={traffic} /> : <p className="text-sm text-muted">No traffic data yet.</p>}
    </section>
  );
}

function TrafficBody({ traffic: t }: { traffic: AdminTraffic }) {
  const shares = t.shares_by_channel ?? {};
  const reportsShared = CHANNELS.reduce((sum, c) => sum + (shares[c.key] ?? 0), 0);
  const tiles: { label: string; value: number; note?: string }[] = [
    { label: "Page views", value: t.page_views },
    { label: "Unique visitors", value: t.unique_visitors },
    {
      label: "Calls started",
      value: t.calls_started,
      note: `${pct(t.calls_started, t.unique_visitors)} calls / visitors`,
    },
    { label: "Calls completed", value: t.calls_completed },
    { label: "Reports shared", value: reportsShared },
    { label: "Shared reports opened", value: t.report_opens },
  ];

  return (
    <>
      <div className="grid grid-cols-2 gap-px border border-line bg-line lg:grid-cols-6">
        {tiles.map((tile) => (
          <div key={tile.label} className="bg-ground p-4">
            <p className="text-sm text-muted">{tile.label}</p>
            <p className="figure num mono mt-2 text-2xl text-ink">{tile.value.toLocaleString()}</p>
            {tile.note && <p className="mt-1 text-xs text-muted">{tile.note}</p>}
          </div>
        ))}
      </div>

      <div className="space-y-3">
        <h3 className="phase">Where events happen</h3>
        <WorldMap points={t.points ?? []} />
      </div>

      <div className="space-y-3">
        <h3 className="phase">Countries</h3>
        {t.by_country.length === 0 ? (
          <p className="text-sm text-muted">No countries yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="mono num w-full min-w-[32rem] border-collapse text-sm">
              <caption className="sr-only">Traffic by country, most views first</caption>
              <thead>
                <tr className="text-left text-muted">
                  {["Country", "Views", "Calls", "Report opens"].map((h, i) => (
                    <th
                      key={h}
                      scope="col"
                      className={`border-b border-line py-2 pr-4 font-normal ${i > 0 ? "text-right" : ""}`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...t.by_country]
                  .sort((a, b) => b.views - a.views)
                  .map((c) => (
                    <tr key={c.country} className="border-b border-line">
                      <td className="py-2 pr-4">
                        <span aria-hidden="true" className="mr-2">
                          {flag(c.country.toUpperCase())}
                        </span>
                        <span className="text-muted">{c.country.toUpperCase()}</span>{" "}
                        <span className="text-ink">{regionName(c.country.toUpperCase())}</span>
                      </td>
                      <td className="py-2 pr-4 text-right">{c.views}</td>
                      <td className="py-2 pr-4 text-right">{c.calls}</td>
                      <td className="py-2 pr-4 text-right">{c.opens}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <div className="space-y-3">
          <h3 className="phase">Shares by channel</h3>
          {reportsShared === 0 ? (
            <p className="text-sm text-muted">No shares yet.</p>
          ) : (
            <BarList
              rows={CHANNELS.map((c) => ({ label: c.label, value: shares[c.key] ?? 0 }))}
              format={(v) => String(v)}
            />
          )}
        </div>
        <div className="space-y-3">
          <h3 className="phase">Top UTM sources</h3>
          {t.utm_sources.length === 0 ? (
            <p className="text-sm text-muted">No UTM sources yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {[...t.utm_sources]
                .sort((a, b) => b.views - a.views)
                .slice(0, 10)
                .map((u) => (
                  <li key={u.source} className="flex items-baseline justify-between gap-4 border-b border-line py-1">
                    <span className="text-ink">{u.source}</span>
                    <span className="mono num text-muted">{u.views} views</span>
                  </li>
                ))}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}

function BarList({ rows, format }: { rows: { label: string; value: number }[]; format: (v: number) => string }) {
  const max = Math.max(...rows.map((r) => r.value), 0.0001);
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label} className="space-y-1">
          <div className="flex items-baseline justify-between gap-4 text-sm">
            <span className="text-ink">{r.label}</span>
            <span className="mono num text-ink">{format(r.value)}</span>
          </div>
          <div aria-hidden="true" className="h-1.5 bg-line">
            <div className="h-full bg-muted" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

const eventLabel = (p: TrafficPoint) => {
  const place = [p.city, p.country].filter(Boolean).join(", ") || "Unknown location";
  return `${place} · ${TYPE_BY_KEY[p.type]?.label ?? p.type}`;
};

function WorldMap({ points }: { points: TrafficPoint[] }) {
  const [enabled, setEnabled] = useState<Set<TrafficEventType>>(() => new Set(TYPES.map((t) => t.key)));
  const [active, setActive] = useState<number | null>(null);

  const located = points.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const counts = Object.fromEntries(TYPES.map((t) => [t.key, located.filter((p) => p.type === t.key).length]));
  // Keep the original index so the tooltip can point back into `located`.
  const visible = located.flatMap((p, i) => (enabled.has(p.type) ? [{ p, i }] : []));
  const countries = new Set(visible.map(({ p }) => p.country).filter(Boolean)).size;
  const summary =
    visible.length === 0
      ? "No located events to show."
      : `${visible.length} events from ${countries} ${countries === 1 ? "country" : "countries"}.`;

  const toggle = (key: TrafficEventType) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setActive(null);
  };

  const hovered = active !== null ? located[active] : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Show event types">
        {TYPES.map((t) => {
          const on = enabled.has(t.key);
          return (
            <button
              key={t.key}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(t.key)}
              className={`mono flex items-center gap-2 border border-line px-3 py-1.5 text-xs ${on ? "text-ink" : "text-muted opacity-60"}`}
            >
              <span
                aria-hidden="true"
                className="inline-block size-2.5 rounded-full"
                style={{ background: t.fill }}
              />
              {t.label} <span className="num">{counts[t.key]}</span>
            </button>
          );
        })}
      </div>

      <div className="relative aspect-[2/1] w-full overflow-hidden border border-line bg-ground">
        {/* Decorative base map: an SVG, so next/image adds nothing here. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={MAP_SRC}
          alt=""
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 h-full w-full"
          style={{ filter: "invert(1)", opacity: 0.18 }}
        />
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="group"
          aria-label={summary}
          className="absolute inset-0 h-full w-full overflow-visible"
          onMouseLeave={() => setActive(null)}
        >
          {visible.map(({ p, i }) => {
            const x = ((p.lon + 180) / 360) * W;
            const y = ((90 - p.lat) / 180) * H;
            const on = active === i;
            return (
              <circle
                key={i}
                cx={x}
                cy={y}
                r={on ? 2.2 : 1.3}
                tabIndex={0}
                role="img"
                aria-label={eventLabel(p)}
                style={{ fill: TYPE_BY_KEY[p.type]?.fill ?? "var(--muted)", cursor: "default" }}
                onMouseEnter={() => setActive(i)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
              />
            );
          })}
        </svg>
        {hovered && active !== null && (
          <div
            aria-hidden="true"
            className="mono pointer-events-none absolute z-10 whitespace-nowrap bg-ink px-2 py-1 text-xs text-ground"
            style={{
              left: `${((hovered.lon + 180) / 360) * 100}%`,
              top: `${((90 - hovered.lat) / 180) * 100}%`,
              transform: "translate(-50%, calc(-100% - 8px))",
            }}
          >
            {eventLabel(hovered)}
          </div>
        )}
      </div>
      <p className="text-sm text-muted">{summary}</p>
    </div>
  );
}
