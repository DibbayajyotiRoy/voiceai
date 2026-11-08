/** Shared driver for the signal line. LiveDemo writes it; SignalLine reads it on each tick. */
export const signal: { level: number; live: boolean } = { level: 0, live: false };

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
