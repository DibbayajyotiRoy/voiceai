"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { prefersReducedMotion, signal } from "@/lib/signal";

const N = 480; // samples across the full width (ring buffer)

/**
 * The line: a recorder trace in pen red. Idle = faint noise, scroll speeds it up,
 * a live call draws the real audio amplitude from signal.level.
 */
export function SignalLine({
  height,
  flat = false,
  className = "",
}: {
  height?: number; // fixed px; omit to take the height from className
  flat?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const still = flat || prefersReducedMotion();
    const samples = new Float32Array(N);
    let head = 0; // oldest sample; the newest sits just before it
    let width = 0;
    let h = height ?? 120; // drawn height in CSS px, measured on resize
    let dpr = 1;
    let energy = 0; // scroll energy 0..1, decays every tick
    let lastY = window.scrollY;
    let running = false;

    const draw = () => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, h);
      const mid = h / 2;
      const pen = getComputedStyle(canvas).getPropertyValue("--pen").trim() || "#c8321c";
      ctx.strokeStyle = pen;
      ctx.lineWidth = 1.5;
      ctx.lineJoin = "round";
      ctx.beginPath();
      for (let i = 0; i < N; i++) {
        const x = (i / (N - 1)) * width;
        const y = mid + samples[(head + i) % N];
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      const last = samples[(head + N - 1) % N];
      ctx.fillStyle = pen;
      ctx.beginPath();
      ctx.arc(width - 2, mid + last, 3, 0, Math.PI * 2);
      ctx.fill();
    };

    const tick = () => {
      const y = window.scrollY;
      const dy = Math.abs(y - lastY);
      lastY = y;
      energy = Math.max(energy * 0.94, Math.min(1, dy / 40));
      const idle = (Math.random() - 0.5) * 4; // about 2px of line noise
      const scroll = (Math.random() - 0.5) * 2 * energy * h * 0.3;
      const voice = (Math.random() - 0.5) * 2 * signal.level * h * 0.4;
      samples[head] = idle + scroll + voice;
      head = (head + 1) % N;
      draw();
    };

    const setRunning = (on: boolean) => {
      if (on === running) return;
      running = on;
      if (on) gsap.ticker.add(tick);
      else gsap.ticker.remove(tick);
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      h = rect.height || h;
      dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(h * dpr);
      draw();
    };
    resize();

    if (still) {
      // One static line, no clock. Flat = dead line (404); reduced motion = gentle wave.
      for (let i = 0; i < N; i++) samples[i] = flat ? 0 : Math.sin((i / N) * Math.PI * 4) * 3;
      draw();
      const ro = new ResizeObserver(resize);
      ro.observe(canvas);
      return () => ro.disconnect();
    }

    // Pause the clock while off-screen.
    const io = new IntersectionObserver(([entry]) => setRunning(entry.isIntersecting));
    io.observe(canvas);
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    return () => {
      io.disconnect();
      ro.disconnect();
      setRunning(false);
    };
  }, [height, flat]);

  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      className={`block w-full ${className}`}
      style={height ? { height } : undefined}
    />
  );
}
