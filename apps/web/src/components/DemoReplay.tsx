"use client";

import { useEffect, useRef, useState } from "react";
import { track } from "@vercel/analytics";
import { demoReplay } from "@/lib/data";

/** Synchronized replay of the local demo call: transcript + state waterfall. */
export function DemoReplay() {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedTracked = useRef(false);

  useEffect(() => {
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  const play = () => {
    setStep(0);
    setPlaying(true);
    if (!startedTracked.current) {
      track("demo_replay_started");
      startedTracked.current = true;
    }
    let next = 0;
    timer.current = setInterval(() => {
      next += 1;
      if (next >= demoReplay.length) {
        if (timer.current) clearInterval(timer.current);
        setPlaying(false);
        track("demo_replay_completed");
        return;
      }
      setStep(next);
    }, 1400);
  };

  return (
    <div className="rounded-lg border border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="font-mono text-xs text-dim">
          replay: services/orchestrator/demo.py — deterministic, offline
        </span>
        <button
          onClick={play}
          disabled={playing}
          className="rounded bg-amber px-3 py-1 font-mono text-xs font-semibold text-ink disabled:opacity-40"
        >
          {playing ? "playing…" : "▶ replay call"}
        </button>
      </div>
      <div className="grid gap-0 md:grid-cols-[1fr_280px]">
        <ol className="divide-y divide-line">
          {demoReplay.slice(0, step + 1).map((turn, i) => (
            <li key={i} className="px-4 py-3">
              <div
                className={
                  turn.speaker === "citizen"
                    ? "font-mono text-sm text-fg"
                    : "font-mono text-sm text-amber"
                }
              >
                {turn.speaker === "citizen" ? "Bürger" : "Charly"}› {turn.text}
              </div>
              <div className="mt-1 font-mono text-[11px] text-dim">
                → {turn.stateNote}
              </div>
            </li>
          ))}
          {step === 0 && !playing && (
            <li className="px-4 py-6 font-mono text-xs text-dim">
              Press replay to watch the call: street-name capture, dictated
              number, correction without reset, RAG grounding, idempotent tool,
              then barge-in handling.
            </li>
          )}
        </ol>
        <div className="border-t border-line p-4 md:border-l md:border-t-0">
          <div className="font-mono text-[11px] uppercase tracking-wider text-dim">
            call state
          </div>
          <ul className="mt-2 space-y-1 font-mono text-[11px]">
            {demoReplay.slice(0, step + 1).map((turn, i) => (
              <li key={i} className="text-dim">
                <span className="text-pass">✓</span> {turn.stateNote}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
