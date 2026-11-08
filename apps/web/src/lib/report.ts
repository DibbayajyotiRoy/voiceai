/** Shapes returned by the call and control backends, plus shared number formatting. */

export type CallReportData = {
  call_id: string;
  started_at: string;
  duration_s: number;
  turns: number;
  interruptions: number;
  greeting_latency_ms: number | null;
  latency_ms: { p50: number; p95: number; min: number; max: number } | null;
  per_turn_ms: number[];
  user_talk_s: number;
  agent_talk_s: number;
  tokens: number | null;
  est_cost_usd: number | null;
  model: string;
  region: string;
  measured_at: string;
  share_id?: string | null;
  latency_basis?: string;
};

export type AdminSummary = {
  backend: { state: "stopped" | "starting" | "ready"; url: string | null };
  totals: {
    calls: number;
    minutes: number;
    est_cost_usd: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
  };
  calls: CallReportData[];
  aws_cost: {
    source: string;
    scope: string;
    month_to_date_usd: number | null;
    daily: { date: string; usd: number }[];
    by_service: { service: string; usd: number }[];
    error: string | null;
  };
};

const NBSP = " ";

export const fmtMs = (ms: number | null | undefined) =>
  ms == null ? "—" : `${Math.round(ms)}${NBSP}ms`;

export const fmtSec = (ms: number | null | undefined) =>
  ms == null ? "—" : `${(ms / 1000).toFixed(2)}${NBSP}s`;

export const fmtSecs = (s: number | null | undefined) =>
  s == null ? "—" : `${s.toFixed(1)}${NBSP}s`;

export function fmtDuration(s: number | null | undefined) {
  if (s == null) return "—";
  const total = Math.round(s);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export const fmtUsd = (v: number | null | undefined, empty = "—") =>
  v == null ? empty : `$${v.toFixed(v < 1 ? 3 : 2)}`;

export const verdict = (p50: number) =>
  p50 < 1000 ? "Feels instant" : p50 <= 2000 ? "Natural pace" : "Noticeable pauses";

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
