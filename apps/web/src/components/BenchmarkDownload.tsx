"use client";

import { track } from "@vercel/analytics";
import { headlineMetrics, loadResult } from "@/lib/data";

/** Download the measured benchmark JSON — fires the benchmark_downloaded event. */
export function BenchmarkDownload() {
  const download = () => {
    const payload = {
      generated_by: "presentation demo mode — sanitized, no infrastructure dependencies",
      reproducible: true,
      metrics: headlineMetrics,
      load_result_laptop_50_concurrent: loadResult,
      commands: headlineMetrics.map((m) => m.command).filter(Boolean),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "voiceai-benchmarks.json";
    a.click();
    URL.revokeObjectURL(url);
    track("benchmark_downloaded");
  };

  return (
    <button
      onClick={download}
      className="rounded border border-amber px-4 py-2 font-mono text-sm text-amber transition-colors hover:bg-amber hover:text-ink"
    >
      ↓ download benchmark JSON
    </button>
  );
}
