"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { CallReport } from "@/components/CallReport";
import type { CallReportData } from "@/lib/report";
import { fmtDuration } from "@/lib/report";
import { getSharedReport } from "@/lib/report-share";
import { ReportOpened } from "./ReportOpened";

// A shared report is looked up by id in the browser (the endpoint is public), so this
// page stays fully static and can be hosted on any static CDN.

export default function SharedReportPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<CallReportData | null>(null);
  const [state, setState] = useState<"loading" | "missing" | "ready">("loading");

  useEffect(() => {
    let live = true;
    getSharedReport(id)
      .then((r) => {
        if (!live) return;
        if (r) {
          setReport(r);
          setState("ready");
        } else {
          setState("missing");
        }
      })
      .catch(() => live && setState("missing"));
    return () => {
      live = false;
    };
  }, [id]);

  if (state === "loading") {
    return (
      <main id="main" className="wrap flex min-h-svh items-center py-4">
        <p className="phase">Loading the call report…</p>
      </main>
    );
  }

  if (state === "missing" || !report) {
    return (
      <main id="main" className="wrap flex min-h-svh flex-col gap-6 py-4">
        <header>
          <Link href="/" className="text-lg font-semibold tracking-tight">
            voiceai
          </Link>
        </header>
        <p className="phase">This call report does not exist (or has expired).</p>
        <div>
          <Link href="/" className="key key--solid">
            Back to the demo <span className="arrow" aria-hidden="true">→</span>
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main id="main" className="wrap flex min-h-svh flex-col gap-10 py-4">
      <header>
        <Link href="/" className="text-lg font-semibold tracking-tight">
          voiceai
        </Link>
      </header>

      <section className="flex flex-col gap-3">
        <p className="phase">
          <time dateTime={report.started_at}>
            {new Date(report.started_at).toLocaleDateString("en-US", {
              dateStyle: "long",
              timeZone: "UTC",
            })}{" "}
            · {fmtDuration(report.duration_s)} call
          </time>
        </p>
        <h1 className="h2 max-w-[20ch] text-[length:var(--t-l)]">A live call with the voiceai agent</h1>
      </section>

      <CallReport report={report} />

      <div>
        <Link
          href="/?utm_source=report&utm_medium=referral&utm_campaign=call_report"
          className="key key--solid"
        >
          Talk to the agent yourself <span className="arrow" aria-hidden="true">→</span>
        </Link>
      </div>

      <ReportOpened shareId={id} />
    </main>
  );
}
