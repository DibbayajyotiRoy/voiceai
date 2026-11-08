import type { ReactNode } from "react";
import { ArchitectureExplorer } from "@/components/ArchitectureExplorer";
import { BenchmarkDownload } from "@/components/BenchmarkDownload";
import { CallHud } from "@/components/CallHud";
import { ContactLink } from "@/components/ContactLink";
import { LifecycleTracker } from "@/components/LifecycleTracker";
import { LiveDemo } from "@/components/LiveDemo";
import { Reveal } from "@/components/Reveal";
import { SignalLine } from "@/components/SignalLine";
import {
  headlineMetrics,
  honestLimitations,
  loadResult,
  runbookExcerpt,
  speechModels,
} from "@/lib/data";

const nav = [
  { id: "demo", label: "Call" },
  { id: "evidence", label: "Evidence" },
  { id: "speech", label: "Speech layer" },
  { id: "architecture", label: "Architecture" },
  { id: "limits", label: "Limits" },
];

/** Grid for every section: label in 3 columns, content in 9. Stacks on phones. */
const grid = "wrap grid gap-y-6 md:grid-cols-12 md:gap-x-[var(--gutter)]";

function Gutter({ phase, children }: { phase: string; children: ReactNode }) {
  return (
    <p className="phase md:col-span-3 md:pt-3">
      <b>{phase}</b> {children}
    </p>
  );
}

function Tag({ status }: { status: "measured" | "pending" }) {
  return status === "measured" ? (
    <span className="mono inline-block bg-ink px-2 py-0.5 text-[11px] font-semibold tracking-wide text-ground">
      MEASURED
    </span>
  ) : (
    <span className="mono inline-block border border-ink px-2 py-0.5 text-[11px] font-semibold tracking-wide text-ink">
      PENDING
    </span>
  );
}

export default function Page() {
  return (
    <>
      <header className="wrap flex items-start justify-between gap-6 pt-6">
        <div>
          <p className="text-lg font-semibold tracking-tight">voiceai</p>
          <p className="phase">case study by Dibbayajyoti Roy</p>
        </div>
        <nav aria-label="Sections" className="flex items-center gap-6 text-sm">
          <a href="#demo" className="trace-link inline-flex min-h-11 items-center">
            Call
          </a>
          <div className="hidden items-center gap-6 md:flex">
            {nav.slice(1).map((item) => (
              <a key={item.id} href={`#${item.id}`} className="trace-link inline-flex min-h-11 items-center">
                {item.label}
              </a>
            ))}
          </div>
          <details className="relative md:hidden">
            <summary className="flex min-h-11 cursor-pointer list-none items-center font-medium [&::-webkit-details-marker]:hidden">
              Menu
            </summary>
            <div className="absolute right-0 top-full z-50 mt-2 flex min-w-48 flex-col border border-line bg-ground p-2">
              {nav.map((item) => (
                <a
                  key={item.id}
                  href={`#${item.id}`}
                  className="flex min-h-11 items-center px-3 text-base"
                >
                  {item.label}
                </a>
              ))}
            </div>
          </details>
        </nav>
      </header>

      <main id="main">
        {/* ------------------------------------------------ hero: discovery */}
        <section data-phase="discovery" className="flex flex-col overflow-x-clip pb-16 md:pb-24">
          <div className={`${grid} pt-16 md:pt-12`}>
            <Gutter phase="discovery">what this call is about</Gutter>
            <div className="space-y-8 md:col-span-9">
              <p className="text-sm font-medium text-muted">
                Engineering case study · German municipal voice AI
              </p>
              <h1 className="display">A phone agent you can call right now.</h1>
              <p className="lede">
                It answers in real time on AWS Nova 2 Sonic. Every claim below is
                either measured, with the command that produced it, or marked pending.
              </p>
              <div className="flex flex-wrap items-center gap-x-8 gap-y-5 pt-2">
                <a href="#demo" className="key key--solid">
                  Call the agent <span className="arrow" aria-hidden="true">→</span>
                </a>
                <a href="#evidence" className="trace-link">
                  Read the evidence
                </a>
              </div>
            </div>
          </div>
          <div className="relative left-1/2 mt-[clamp(32px,6vh,72px)] w-screen -translate-x-1/2">
            <SignalLine className="h-20 md:h-30" />
          </div>
        </section>

        {/* ------------------------------------------------ booth: discovery */}
        <section id="demo" data-phase="discovery" data-slot="demo" className="booth py-28">
          <div className={grid}>
            <Gutter phase="discovery">what to ask it</Gutter>
            <div className="space-y-10 md:col-span-9">
              <div className="space-y-6">
                <h2 className="h2" data-trace>
                  Talk to it.
                </h2>
                <p className="lede">
                  Press call, allow the microphone, and ask what you would ask the
                  engineer: what it is for, where it fits, how it handles interruptions.
                  The agent sleeps when nobody calls, so the first ring takes about a minute.
                </p>
              </div>
              <LiveDemo />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ evidence: collecting */}
        <section id="evidence" data-phase="collecting" data-slot="evidence" className="pb-20 pt-24">
          <div className={grid}>
            <Gutter phase="collecting">every number has a command or a pending tag</Gutter>
            <div className="space-y-10 md:col-span-9">
              <h2 className="h2" data-trace>
                Evidence, not adjectives.
              </h2>
              <div className="grid gap-px border border-line bg-line md:grid-cols-2">
                {headlineMetrics.map((m) => (
                  <div key={m.label} className="flex flex-col gap-3 bg-ground p-6">
                    <div className="flex items-start justify-between gap-3">
                      <span className="mono text-[12px] uppercase tracking-wide text-muted">
                        {m.label}
                      </span>
                      <Tag status={m.status} />
                    </div>
                    <p
                      className={`figure num text-[length:var(--t-l)] ${
                        m.status === "pending" ? "figure--pending" : ""
                      }`}
                    >
                      {m.value}
                    </p>
                    {m.command && (
                      <code className="mono break-all text-sm text-muted">$ {m.command}</code>
                    )}
                    {m.note && <p className="text-base text-muted">{m.note}</p>}
                  </div>
                ))}
              </div>
              <BenchmarkDownload />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ speech: collecting */}
        <section id="speech" data-phase="collecting" className="pb-24">
          <div className={grid}>
            <Gutter phase="collecting">which speech models were compared</Gutter>
            <div className="space-y-10 md:col-span-9">
              <div className="space-y-6">
                <h2 className="h2" data-trace>
                  Speech layer
                </h2>
                <p className="lede">
                  Open models, self-hosted on EU GPUs, chosen from a manifest-driven
                  comparison. Evaluation runs on telephony-degraded audio (8 kHz,
                  G.711 μ-law, seeded noise) with speaker-group-leakage-safe splits,
                  because clean-studio WER is not phone-call WER.
                </p>
              </div>
              <ul className="border-b border-line">
                {speechModels.map((row) => (
                  <li
                    key={row.model}
                    className="grid gap-3 border-t border-line py-6 md:grid-cols-12 md:gap-6"
                  >
                    <p className="mono break-all text-sm font-medium md:col-span-4">
                      {row.model}
                    </p>
                    <p className="text-base text-muted md:col-span-2">
                      {row.family}, {row.params}
                    </p>
                    <p className="text-base text-muted md:col-span-2">German: {row.german}</p>
                    <p className="text-base text-muted md:col-span-2">{row.license}</p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 md:col-span-2">
                      <Tag status={row.status} />
                      <span className="mono text-xs text-muted">{row.werTelephony}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ limits: confirming */}
        <section id="limits" data-phase="confirming" data-slot="limits" className="py-32">
          <div className={grid}>
            <Gutter phase="confirming">the claims we stop short of</Gutter>
            <div className="md:col-span-9">
              <h2 className="h2" data-trace>
                What is not claimed.
              </h2>
              <ul className="mt-12 max-w-[42ch]">
                {honestLimitations.map((item) => (
                  <li
                    key={item}
                    data-trace
                    className="border-t border-line py-7 text-[length:var(--t-m)] leading-snug"
                  >
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ architecture: executing */}
        <section id="architecture" data-phase="executing" data-slot="architecture" className="pb-28">
          <div className={grid}>
            <Gutter phase="executing">how one call is wired</Gutter>
            <div className="space-y-10 md:col-span-9">
              <div className="space-y-6">
                <h2 className="h2" data-trace>
                  Architecture
                </h2>
                <p className="lede">
                  One pipeline per call, strict layer boundaries, and contracts that let
                  providers change without touching orchestration. Hover or tab through
                  the nodes. Each one says why it exists.
                </p>
              </div>
              <ArchitectureExplorer />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ load: executing */}
        <section id="load" data-phase="executing" className="py-16">
          <div className={grid}>
            <Gutter phase="executing">what happens at 200 calls</Gutter>
            <div className="space-y-12 md:col-span-9">
              <h2 className="h2 max-w-[24ch]" data-trace>
                <span className="figure num">{loadResult.requested}</span> calls rang at once.{" "}
                <span className="figure num">{loadResult.admitted}</span> were answered.{" "}
                <span className="figure num">{loadResult.rejected}</span> heard a busy signal.{" "}
                <span className="figure num">0</span> errors.
              </h2>
              <p className="mono text-sm text-muted">
                orchestration only, fake providers, p50 {loadResult.p50Ms} ms / p95{" "}
                {loadResult.p95Ms} ms
              </p>
              <div>
                <p className="mono mb-5 text-sm text-muted">
                  Debugging runbook. First check per symptom.
                </p>
                <dl className="grid gap-x-12 gap-y-6 md:grid-cols-2">
                  {runbookExcerpt.map((r) => (
                    <div key={r.symptom} className="border-t border-line pt-4">
                      <dt className="font-semibold">{r.symptom}</dt>
                      <dd className="mono mt-1 text-sm text-muted">{r.firstCheck}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* ------------------------------------------------ footer: completed */}
      <footer data-phase="completed">
        <div className={`${grid} border-t border-line pb-44 pt-40 md:pb-48`}>
          <Gutter phase="completed">what to do next</Gutter>
          <div className="space-y-10 md:col-span-9">
            <h2 className="display" data-trace>
              Hand off to a human.
            </h2>
            <div className="flex flex-wrap items-center gap-x-8 gap-y-5">
              <ContactLink />
              <a
                href="https://github.com/DibbayajyotiRoy/voiceai"
                target="_blank"
                rel="noopener noreferrer"
                className="trace-link"
              >
                github.com/DibbayajyotiRoy/voiceai
              </a>
            </div>
            <p className="max-w-[60ch] text-base text-muted">
              The page itself loads no S3, no PostgreSQL and no provider keys. Live
              inference only runs when you start a call, on an AWS task that scales to
              zero. Analytics count visits, never people.
            </p>
          </div>
        </div>
      </footer>

      <CallHud />
      <Reveal />
      <LifecycleTracker />
    </>
  );
}
