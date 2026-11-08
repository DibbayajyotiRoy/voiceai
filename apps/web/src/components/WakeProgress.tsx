import { useState } from "react";

// Server stages in the order the control API reports them. Bands are the share of the bar;
// `typical` is how long a stage usually takes, used only to pace the estimate.
const STEPS = [
  { stage: "provisioning", label: "Starting server", lo: 0, hi: 15, typical: 15 },
  { stage: "pulling", label: "Loading the agent", lo: 15, hi: 55, typical: 25 },
  { stage: "starting", label: "Booting", lo: 55, hi: 75, typical: 10 },
  { stage: "securing", label: "Securing the line", lo: 75, hi: 97, typical: 40 },
] as const;

const LONG_WAIT_S = 150;

/** Fill (0..97) for the current stage. Unknown stage (older backend): elapsed time only. */
function estimate(idx: number, stageS: number, secs: number) {
  if (idx < 0) return 97 * (1 - Math.exp(-secs / 60));
  const s = STEPS[idx];
  // Reaches 95% of its band at the typical duration and keeps creeping, so it never stalls.
  return s.lo + (s.hi - s.lo) * (1 - Math.exp((-3 * stageS) / s.typical));
}

type Props = { stage: string | null; sinceS: number | null; elapsed: number };

export function WakeProgress({ stage, sinceS, elapsed }: Props) {
  const idx = STEPS.findIndex((s) => s.stage === stage);
  const secs = Math.floor(sinceS ?? elapsed);
  // Seconds at which the current stage was first seen; the parent re-renders every second.
  const [entered, setEntered] = useState({ stage, at: secs });
  if (entered.stage !== stage) setEntered({ stage, at: secs });
  const stageS = secs - entered.at;
  const pct = stage === "ready" ? 100 : estimate(idx, stageS, secs);
  const current = idx >= 0 ? STEPS[idx] : null;
  const stepText =
    secs > LONG_WAIT_S
      ? "Taking longer than usual. Still trying…"
      : `${current ? current.label : "Waking the agent"}…`;

  return (
    <div className="flex w-full max-w-[52ch] flex-col items-center gap-4">
      <ol
        aria-label="Wake progress"
        className="mono flex w-full flex-wrap justify-center gap-x-4 gap-y-2 text-[0.8125rem] min-[480px]:justify-between"
      >
        {STEPS.map((s, i) => {
          const done = idx > i;
          const now = idx === i;
          return (
            <li
              key={s.stage}
              aria-current={now ? "step" : undefined}
              className={`flex items-center gap-2 ${now ? "" : "max-[479px]:hidden"} ${
                done ? "text-ink" : now ? "text-pen" : "text-muted"
              }`}
            >
              {done ? (
                <svg
                  aria-hidden="true"
                  width="10"
                  height="10"
                  viewBox="0 0 10 10"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                >
                  <path d="M1.5 5.2 4 7.6 8.5 2.4" />
                </svg>
              ) : (
                <span
                  aria-hidden="true"
                  className={`inline-block size-1.5 rounded-full ${now ? "wake-dot bg-pen" : "border border-muted"}`}
                />
              )}
              {s.label}
            </li>
          );
        })}
      </ol>
      {current && (
        <p className="mono text-[0.8125rem] text-muted min-[480px]:hidden">
          step {idx + 1} of {STEPS.length}
        </p>
      )}
      <div aria-hidden="true" className="h-[2px] w-full overflow-hidden bg-line">
        <div className="wake-bar h-full w-full origin-left bg-pen" style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
      <p role="status" aria-live="polite" className="mono text-center text-sm text-muted">
        {stepText} <span aria-hidden="true">{secs}s</span>
      </p>
      <p className="mono max-w-[52ch] text-center text-sm text-muted">
        Waking the agent on AWS. First call takes up to two minutes; it sleeps when unused.
      </p>
      <p className="mono max-w-[52ch] text-center text-sm text-muted">
        Honestly, I don&apos;t have enough money to keep AWS running it all day.
      </p>
    </div>
  );
}
