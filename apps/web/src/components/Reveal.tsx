"use client";

import { useEffect } from "react";

const SAFETY_MS = 2500;

/**
 * Traces each [data-trace] element once. CSS does the wipe.
 * Safety net: anything above the viewport bottom is traced on mount, on every
 * observer callback, and 2.5s after mount, so no text stays hidden.
 */
export function Reveal() {
  useEffect(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>("[data-trace]"));
    const traceAbove = () => {
      for (const el of els) {
        if (!el.classList.contains("is-traced") && el.getBoundingClientRect().top < window.innerHeight) {
          el.classList.add("is-traced");
        }
      }
    };
    if (!("IntersectionObserver" in window)) {
      els.forEach((el) => el.classList.add("is-traced"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          e.target.classList.add("is-traced");
          io.unobserve(e.target);
        }
        traceAbove();
      },
      { threshold: 0, rootMargin: "0px 0px -8% 0px" },
    );
    els.forEach((el) => io.observe(el));
    traceAbove();
    const timer = window.setTimeout(traceAbove, SAFETY_MS);
    return () => {
      io.disconnect();
      window.clearTimeout(timer);
    };
  }, []);
  return null;
}
