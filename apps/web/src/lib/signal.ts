/**
 * Shared driver for the signal line and the orb. LiveDemo writes it on each tick.
 * level = max(mic, agent); mic and agent are 0..1 RMS of each side of the call.
 */
export const signal: { level: number; mic: number; agent: number; live: boolean } = {
  level: 0,
  mic: 0,
  agent: 0,
  live: false,
};

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
