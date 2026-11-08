import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CallReport } from "@/components/CallReport";
import { fmtDuration, fmtSec } from "@/lib/report";
import { getSharedReport } from "@/lib/report-share";
import { ReportOpened } from "./ReportOpened";

type Props = { params: Promise<{ id: string }> };

// A shared report is looked up by id at request time (cached an hour), so it is not an instant navigation.
export const instant = false;

const medianOf = (p50: number | null | undefined) => (p50 == null ? null : fmtSec(p50));

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const report = await getSharedReport(id);
  const median = medianOf(report?.latency_ms?.p50);
  const title = median ? `${median} median reply on a live voice AI call` : "Call report";
  const description = "A live call with the voiceai agent: reply times for every turn, measured on the server.";
  return {
    title,
    description,
    robots: { index: false, follow: false },
    alternates: { canonical: `/r/${id}` },
    openGraph: { title, description, url: `/r/${id}` },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function SharedReportPage({ params }: Props) {
  const { id } = await params;
  const report = await getSharedReport(id);
  if (!report) notFound();

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
