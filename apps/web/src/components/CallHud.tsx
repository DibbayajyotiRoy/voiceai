"use client";

import { useEffect, useState } from "react";
import { gsap } from "gsap";

type Slot = "demo" | "evidence" | "limits" | "architecture";
type SlotStatus = "missing" | "provisional" | "confirmed";

const SLOTS: Slot[] = ["demo", "evidence", "limits", "architecture"];

const square: Record<SlotStatus, string> = {
  missing: "border border-muted",
  provisional: "border border-pen",
  confirmed: "border border-ink bg-ink",
};

const clock = (secs: number) =>
  `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;

/** Corner state machine: which call phase the reader is in, and which slots are filled. */
export function CallHud() {
  const [phase, setPhase] = useState("discovery");
  const [slots, setSlots] = useState<Record<Slot, SlotStatus>>({
    demo: "missing",
    evidence: "missing",
    limits: "missing",
    architecture: "missing",
  });
  const [secs, setSecs] = useState(0);

  // Seconds since page load, on the shared clock.
  useEffect(() => {
    const start = performance.now();
    let last = -1;
    const tick = () => {
      const s = Math.floor((performance.now() - start) / 1000);
      if (s !== last) {
        last = s;
        setSecs(s);
      }
    };
    gsap.ticker.add(tick);
    return () => gsap.ticker.remove(tick);
  }, []);

  // Phase: the section crossing the middle band of the viewport.
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setPhase((e.target as HTMLElement).dataset.phase ?? "discovery");
        }
      },
      { rootMargin: "-45% 0px -45% 0px" },
    );
    document.querySelectorAll<HTMLElement>("[data-phase]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  // Slots: provisional while in view, confirmed once scrolled past.
  useEffect(() => {
    const io = new IntersectionObserver((entries) => {
      setSlots((prev) => {
        let next = prev;
        for (const e of entries) {
          const slot = (e.target as HTMLElement).dataset.slot as Slot;
          if (next[slot] === "confirmed") continue;
          const status: SlotStatus = e.isIntersecting
            ? "provisional"
            : e.boundingClientRect.top < 0
              ? "confirmed"
              : next[slot];
          if (status !== next[slot]) next = { ...next, [slot]: status };
        }
        return next;
      });
    });
    document.querySelectorAll<HTMLElement>("[data-slot]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return (
    <div
      className="fixed z-50 flex items-center gap-2.5 overflow-hidden whitespace-nowrap border border-line bg-ground px-3 py-2 font-mono text-[12px] text-muted sm:max-w-[min(300px,calc(25vw-var(--gutter)))]"
      style={{ left: "var(--gutter)", bottom: "var(--gutter)", maxWidth: "calc(100vw - 2 * var(--gutter))" }}
    >
      <span className="min-w-0 truncate">
        phase <b className="font-semibold text-pen">{phase}</b>
      </span>
      <span className="hidden items-center gap-1 sm:flex" role="list" aria-label="Slots">
        {SLOTS.map((name) => (
          <span
            key={name}
            role="listitem"
            title={`${name}: ${slots[name]}`}
            className={`block h-2.5 w-2.5 ${square[slots[name]]}`}
          >
            <span className="sr-only">
              {name} {slots[name]}
            </span>
          </span>
        ))}
      </span>
      <span className="num text-ink">{clock(secs)}</span>
    </div>
  );
}
