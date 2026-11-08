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
    <div className="border border-line">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-5 py-4">
        <span className="mono text-xs text-muted">
          replay: services/orchestrator/demo.py. Deterministic, offline.
        </span>
        <button
          onClick={play}
          disabled={playing}
          className="key"
          style={{ minHeight: 40, padding: "0 1rem", fontSize: "0.875rem" }}
        >
          {playing ? "playing…" : "▶ replay call"}
        </button>
      </div>
      <div className="grid md:grid-cols-[1fr_300px]">
        <ol className="divide-y divide-line">
          {demoReplay.slice(0, step + 1).map((turn, i) => (
            <li key={i} className="px-5 py-4">
              <div
                className={`mono text-xs font-semibold uppercase tracking-wide ${
                  turn.speaker === "citizen" ? "text-ink" : "text-pen"
                }`}
              >
                {turn.speaker === "citizen" ? "Citizen" : "Agent"}
              </div>
              <p className="mt-1 text-base">{turn.text}</p>
              <p className="mono mt-1 text-xs text-muted">→ {turn.stateNote}</p>
            </li>
          ))}
          {step === 0 && !playing && (
            <li className="mono px-5 py-6 text-sm text-muted">
              Press replay to watch the call: street-name capture, dictated number,
              correction without reset, RAG grounding, idempotent tool, then barge-in
              handling.
            </li>
          )}
        </ol>
        <div className="border-t border-line p-5 md:border-l md:border-t-0">
          <div className="mono text-xs uppercase tracking-wider text-muted">call state</div>
          <ul className="mono mt-3 space-y-2 text-xs text-muted">
            {demoReplay.slice(0, step + 1).map((turn, i) => (
              <li key={i}>
                <span className="text-pen">✓</span> {turn.stateNote}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
