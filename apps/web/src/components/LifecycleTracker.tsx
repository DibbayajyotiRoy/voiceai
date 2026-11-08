"use client";

import { useEffect } from "react";
import { track } from "@vercel/analytics";

/** Fires lifecycle events exactly once per page load. */
export function LifecycleTracker() {
  useEffect(() => {
    track("presentation_started");
    const onScroll = () => {
      if (
        window.innerHeight + window.scrollY >=
        document.body.scrollHeight - 40
      ) {
        track("presentation_completed");
        window.removeEventListener("scroll", onScroll);
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return null;
}
