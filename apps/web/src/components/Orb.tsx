"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { prefersReducedMotion, signal } from "@/lib/signal";

export type OrbPhase = "idle" | "waking" | "connecting" | "live" | "error";

const TAU = Math.PI * 2;
const RING_S = 3.2; // ring pulse period, seconds
const BREATH_S = 5; // idle breath period, seconds
const FALLBACK_PEN: RGB = [200, 50, 28];

type RGB = [number, number, number];

function hexToRgb(hex: string): RGB {
  const h = hex.trim().replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  const n = parseInt(full, 16);
  return Number.isNaN(n) ? FALLBACK_PEN : [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const rgba = (c: RGB, a: number) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const tint = (a: RGB, b: RGB, t: number): RGB => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
];
const WHITE: RGB = [255, 255, 255];
const INK: RGB = [18, 21, 19];

/**
 * The call control: a glowing pen-red sphere drawn on canvas.
 * All motion runs on gsap.ticker. Idle = slow breath, waking/connecting = ring pulse,
 * live = surface deforms with signal.level (mic + agent audio).
 * Reduced motion: one static frame, state is carried by the status text.
 */
export function Orb({
  phase,
  enabled,
  label,
  onClick,
}: {
  phase: OrbPhase;
  enabled: boolean;
  label: string;
  onClick: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const phaseRef = useRef(phase);
  const enabledRef = useRef(enabled);
  const redrawRef = useRef<(() => void) | null>(null);

  // Draw loop and sizing. Runs once; reads the latest phase and enabled from refs.
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const still = prefersReducedMotion();
    const pen = hexToRgb(getComputedStyle(canvas).getPropertyValue("--pen"));
    let size = 0; // CSS px
    let dpr = 1;
    let smooth = 0; // eased signal level

    const draw = (t: number) => {
      const phase = phaseRef.current;
      const live = phase === "live";
      const pulsing = phase === "waking" || phase === "connecting";
      smooth += ((live && !still ? signal.level : 0) - smooth) * 0.2;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);
      ctx.globalAlpha = !enabledRef.current ? 0.35 : phase === "error" ? 0.6 : 1;

      const cx = size / 2;
      const cy = size / 2;
      const r = size * 0.3;

      if (pulsing && !still) {
        const f = (t % RING_S) / RING_S;
        ctx.strokeStyle = rgba(pen, (1 - f) * 0.5);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(cx, cy, r * (1.05 + 0.5 * f), 0, TAU);
        ctx.stroke();
      }

      const R = still ? r : r * (1 + 0.02 * Math.sin((t / BREATH_S) * TAU));

      const glow = ctx.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 1.5);
      glow.addColorStop(0, rgba(pen, 0.2 + 0.3 * smooth));
      glow.addColorStop(1, rgba(pen, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.5, 0, TAU);
      ctx.fill();

      // Surface: a few low harmonics, amplitude follows the audio level.
      ctx.beginPath();
      for (let i = 0; i <= 120; i++) {
        const a = (i / 120) * TAU;
        const wob =
          smooth *
          (0.06 * Math.sin(3 * a + t * 1.4) +
            0.04 * Math.sin(5 * a - t * 1.9) +
            0.02 * Math.sin(8 * a + t * 2.6));
        const rr = R * (1 + wob);
        const x = cx + rr * Math.cos(a);
        const y = cy + rr * Math.sin(a);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();

      // Body: the highlight drifts slowly, the edge falls off into shade.
      const hx = cx + R * (-0.32 + 0.06 * Math.sin(t * 0.31));
      const hy = cy + R * (-0.36 + 0.05 * Math.cos(t * 0.23));
      const body = ctx.createRadialGradient(hx, hy, R * 0.06, cx, cy, R * 1.25);
      body.addColorStop(0, rgba(tint(pen, WHITE, 0.5), 1));
      body.addColorStop(0.55, rgba(pen, 1));
      body.addColorStop(1, rgba(tint(pen, INK, 0.45), 1));
      ctx.fillStyle = body;
      ctx.fill();
    };

    const tick = () => draw(gsap.ticker.time);
    redrawRef.current = () => draw(0);

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      size = rect.width;
      dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(size * dpr);
      canvas.height = Math.round(size * dpr);
      redrawRef.current?.();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    if (!still) gsap.ticker.add(tick);
    return () => {
      ro.disconnect();
      gsap.ticker.remove(tick);
      redrawRef.current = null;
    };
  }, []);

  // Keep the loop's inputs current; in reduced motion this is also the only redraw.
  useEffect(() => {
    phaseRef.current = phase;
    enabledRef.current = enabled;
    redrawRef.current?.();
  }, [phase, enabled]);

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!enabled}
      aria-label={label}
      className="relative block aspect-square w-[min(56vmin,420px)] cursor-pointer rounded-full p-0 disabled:cursor-not-allowed"
    >
      <canvas ref={canvasRef} aria-hidden="true" className="absolute inset-0 size-full" />
    </button>
  );
}
