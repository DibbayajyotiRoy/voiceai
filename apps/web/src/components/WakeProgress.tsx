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

// `sinceS` is the server's task age: it can predate the click, so it only paces the bar.
// `elapsed` is time since the user's click and is the only clock shown.
type Props = { stage: string | null; sinceS: number | null; elapsed: number };

export function WakeProgress({ stage, sinceS, elapsed }: Props) {
  const idx = STEPS.findIndex((s) => s.stage === stage);
  const paceS = Math.floor(sinceS ?? elapsed);
  // Pace-seconds at which the current stage was first seen; the parent re-renders every second.
  const [entered, setEntered] = useState({ stage, at: paceS });
  if (entered.stage !== stage) setEntered({ stage, at: paceS });
  const stageS = paceS - entered.at;
  const pct = stage === "ready" ? 100 : estimate(idx, stageS, paceS);
  const current = idx >= 0 ? STEPS[idx] : null;
  const longWait = elapsed > LONG_WAIT_S;
  const label = longWait
    ? "Taking longer than usual. Still trying…"
    : current
      ? current.label
      : "Waking the agent";

  return (
    <div className="flex w-full max-w-[52ch] flex-col items-center gap-4">
      <div
        role="status"
        aria-live="polite"
        className="mono flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-sm"
      >
        <span aria-hidden="true" className="wake-dot inline-block size-1.5 rounded-full bg-pen" />
        <span key={label} className="wake-label inline-block text-ink">
          {label}
        </span>
        {!longWait && current && <span className="text-muted">step {idx + 1} of {STEPS.length}</span>}
        <span aria-hidden="true" className="text-muted">
          {elapsed}s
        </span>
      </div>
      <div aria-hidden="true" className="h-[2px] w-full overflow-hidden bg-line">
        <div className="wake-bar h-full w-full origin-left bg-pen" style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
      <p className="mono max-w-[44rem] text-center text-sm text-muted">
        Waking the agent on AWS. First call takes up to two minutes; it sleeps when unused because I don&apos;t have
        enough money to keep AWS running it all day.
      </p>
    </div>
  );
}
