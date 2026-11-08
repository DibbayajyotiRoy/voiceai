/**
 * Shared driver for the signal line and the orb. LiveDemo writes it on each tick.
 * level = max(mic, agent); mic and agent are 0..1 RMS of each side of the call.
 * voice / hiss: 0..1 energy of the agent's spectrum in the speech band (300 to 3400 Hz)
 * and above it (sibilants), so the orb can move with the frequency content.
 */
export const signal: {
  level: number;
  mic: number;
  agent: number;
  voice: number;
  hiss: number;
  live: boolean;
} = {
  level: 0,
  mic: 0,
  agent: 0,
  voice: 0,
  hiss: 0,
  live: false,
};

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
