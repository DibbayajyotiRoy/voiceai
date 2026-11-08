"use client";

import { useEffect, useRef, type Ref } from "react";
import Script from "next/script";
import { gsap } from "gsap";
import { prefersReducedMotion, signal } from "@/lib/signal";

export type OrbState = "idle" | "waking" | "connecting" | "listening" | "speaking" | "ended" | "disabled";

type Vendor = "listening" | "thinking" | "searching" | "speaking" | "done";
const VENDOR_ORDER: Vendor[] = ["listening", "thinking", "searching", "speaking", "done"];
const VENDOR: Record<OrbState, Vendor> = {
  idle: "listening",
  waking: "searching",
  connecting: "thinking",
  listening: "listening",
  speaking: "speaking",
  ended: "done",
  disabled: "listening",
};

/** The vendored element's public surface we touch (see public/vendor/speaking-orb.js). */
type OrbEl = HTMLElement & {
  envFn?: () => number;
  weights?: number[];
  draw?: (t: number) => void;
  start?: () => void;
};

/**
 * The call control: the vendored speaking-orb renders the sphere inside the button.
 * Our states map onto its states; the level attribute follows the mic or agent signal.
 * Reduced motion: the element is painted once per state change and its clock stops.
 */
export function Orb({
  state,
  enabled,
  label,
  onClick,
  buttonRef,
}: {
  state: OrbState;
  enabled: boolean;
  label: string;
  onClick: () => void;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  const elRef = useRef<OrbEl>(null);
  const stateRef = useRef(state);

  // Reduced motion: one static frame, drawn again only when the state changes.
  const applyStill = () => {
    const el = elRef.current;
    if (!el?.draw || !prefersReducedMotion()) return;
    el.setAttribute("particles", "200");
    el.setAttribute("recording", "");
    el.setAttribute("level", "0");
    const v = VENDOR[stateRef.current];
    el.weights = VENDOR_ORDER.map((n) => (n === v ? 1 : 0));
    el.draw(0);
  };

  useEffect(() => {
    stateRef.current = state;
    applyStill();
  }, [state]);

  // Level follows the signal every frame; off-screen the element's own loop is paused.
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const still = prefersReducedMotion();
    let lastLevel = "";
    // Speech-band energy drives the swell and a ring per syllable (see "voiceai patch").
    el.envFn = () => (stateRef.current === "speaking" ? signal.voice : 0);
    const tick = () => {
      const s = stateRef.current;
      // Speaking: sibilant energy adds fast surface ripple on top of loudness.
      const level =
        s === "ended" || s === "disabled"
          ? 0
          : s === "listening"
            ? signal.mic
            : s === "speaking"
              ? Math.min(1, signal.agent * 0.6 + signal.hiss * 1.2)
              : 0.15;
      const v = level.toFixed(3);
      if (v !== lastLevel) {
        el.setAttribute("level", v);
        lastLevel = v;
      }
    };
    if (still) return;
    gsap.ticker.add(tick);

    let paused = false;
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && paused) {
        paused = false;
        el.removeAttribute("recording");
        el.start?.();
      } else if (!entry.isIntersecting && !paused) {
        paused = true;
        el.setAttribute("recording", "");
      }
    });
    io.observe(el);
    return () => {
      io.disconnect();
      gsap.ticker.remove(tick);
    };
  }, []);

  return (
    <>
      <Script src="/vendor/speaking-orb.js" strategy="afterInteractive" onLoad={applyStill} />
      <button
        ref={buttonRef}
        type="button"
        onClick={onClick}
        disabled={!enabled}
        aria-label={label}
        className="relative block aspect-square w-[min(56vmin,420px)] cursor-pointer rounded-full p-0 disabled:cursor-not-allowed"
      >
        <speaking-orb
          ref={elRef}
          aria-hidden="true"
          state={VENDOR[state]}
          particles="900"
          className="block size-full"
          style={{ opacity: state === "disabled" ? 0.35 : 1 }}
        />
      </button>
    </>
  );
}
