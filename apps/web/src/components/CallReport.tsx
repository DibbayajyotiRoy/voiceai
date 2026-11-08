import {
  fmtDuration,
  fmtMs,
  fmtSec,
  fmtSecs,
  fmtUsd,
  verdict,
  type CallReportData,
} from "@/lib/report";

const SLOW_MS = 2000;

/** Post-call report: headline latency, three stats, a table, and one bar per turn. Pass onAgain to show "Call again". */
export function CallReport({ report, onAgain }: { report: CallReportData; onAgain?: () => void }) {
  const lat = report.latency_ms;
  const p50 = lat?.p50 ?? null;
  const turns = report.per_turn_ms ?? [];
  const maxTurn = Math.max(1, ...turns);

  const rows: [string, string][] = [
    ["First greeting", fmtMs(report.greeting_latency_ms)],
    ["Fastest reply", fmtMs(lat?.min)],
    ["Median reply", fmtMs(lat?.p50)],
    ["95th percentile reply", fmtMs(lat?.p95)],
    ["Slowest reply", fmtMs(lat?.max)],
    ["You talked", fmtSecs(report.user_talk_s)],
    ["Agent talked", fmtSecs(report.agent_talk_s)],
    ["Model", report.model],
    ["Estimated cost", fmtUsd(report.est_cost_usd, "not measured")],
  ];

  const summary =
    p50 == null
      ? `Reply times for ${turns.length} turns, not measured.`
      : `Reply time for each of ${turns.length} turns. Median ${fmtSec(p50)}, slowest ${fmtMs(lat?.max)}.`;

  return (
    <section aria-labelledby="report-title" className="w-full max-w-[52ch] border-t border-line pt-6 text-left">
      <h2 id="report-title" className="phase">
        Call report
      </h2>

      <div className="mt-3">
        <p className="figure num text-[length:var(--t-xl)] text-ink">{p50 == null ? "—" : fmtSec(p50)}</p>
        <p className="mt-1 text-sm text-muted">median reply after you finish</p>
        {p50 != null && <p className="mt-1 text-[length:var(--t-m)] text-ink">{verdict(p50)}</p>}
      </div>

      <dl className="mt-6 grid grid-cols-3 gap-4 border-y border-line py-4">
        <div>
          <dt className="text-sm text-muted">call length</dt>
          <dd className="mono num mt-1 text-ink">{fmtDuration(report.duration_s)}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted">turns</dt>
          <dd className="mono num mt-1 text-ink">{report.turns}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted">interruptions</dt>
          <dd className="mono num mt-1 text-ink">{report.interruptions}</dd>
        </div>
      </dl>

      <table className="mt-6 w-full border-collapse text-sm">
        <caption className="phase mb-2 text-left">Timing and talk time</caption>
        <thead>
          <tr className="text-left text-muted">
            <th scope="col" className="pb-2 font-normal">
              Measure
            </th>
            <th scope="col" className="pb-2 text-right font-normal">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-t border-line">
              <th scope="row" className="py-2 text-left font-normal text-muted">
                {label}
              </th>
              <td className="mono num py-2 text-right text-ink">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {turns.length > 0 && (
        <div className="mt-6">
          <p className="phase mb-2">Reply time per turn</p>
          <svg
            role="img"
            aria-label={summary}
            viewBox={`0 0 ${turns.length * 6} 48`}
            preserveAspectRatio="none"
            className="block h-12 w-full"
          >
            {turns.map((ms, i) => {
              const h = Math.max(1, (ms / maxTurn) * 48);
              return (
                <rect
                  key={i}
                  x={i * 6}
                  y={48 - h}
                  width={4}
                  height={h}
                  style={{ fill: ms > SLOW_MS ? "var(--pen)" : "var(--muted)" }}
                />
              );
            })}
          </svg>
        </div>
      )}

      <p className="mt-6 text-xs text-muted">
        Measured on the server from when the model decided you had finished speaking to its first audio. The
        model&apos;s own wait to be sure you stopped (often half a second to a second) and network time are not
        included.
      </p>

      {onAgain && (
        <button type="button" onClick={onAgain} className="key mt-6">
          Call again
        </button>
      )}
    </section>
  );
}
