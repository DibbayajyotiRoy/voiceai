import { ArchitectureExplorer } from "@/components/ArchitectureExplorer";
import { BenchmarkDownload } from "@/components/BenchmarkDownload";
import { ContactLink } from "@/components/ContactLink";
import { LiveDemo } from "@/components/LiveDemo";
import { LifecycleTracker } from "@/components/LifecycleTracker";
import {
  honestLimitations,
  loadResult,
  runbookExcerpt,
  speechModels,
  headlineMetrics,
} from "@/lib/data";

const sections = [
  { id: "thesis", label: "Thesis" },
  { id: "architecture", label: "Architecture" },
  { id: "speech", label: "Speech layer" },
  { id: "demo", label: "Call replay" },
  { id: "load", label: "Load & admission" },
  { id: "limits", label: "Honest limits" },
];

function StatusBadge({ status }: { status: "measured" | "pending" }) {
  return status === "measured" ? (
    <span className="rounded-sm bg-pass/15 px-2 py-0.5 font-mono text-[11px] text-pass">
      MEASURED
    </span>
  ) : (
    <span className="rounded-sm bg-pend/15 px-2 py-0.5 font-mono text-[11px] text-pend">
      PENDING
    </span>
  );
}

export default function Page() {
  return (
    <div className="mx-auto flex w-full max-w-6xl gap-10 px-6">
      <LifecycleTracker />
      <nav className="sticky top-0 hidden h-screen w-40 shrink-0 flex-col justify-center gap-3 self-start md:flex">
        {sections.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="font-mono text-xs text-dim transition-colors hover:text-amber"
          >
            {s.label}
          </a>
        ))}
      </nav>

      <main className="min-w-0 flex-1 space-y-24 py-16">
        {/* ------------------------------------------------ thesis */}
        <section id="thesis" className="space-y-8">
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-amber">
            engineering case study · German municipal voice AI
          </p>
          <h1 className="max-w-2xl text-4xl font-semibold leading-tight md:text-5xl">
            A phone agent that survives real citizens — built to be measured,
            not demoed.
          </h1>
          <p className="max-w-2xl text-lg leading-relaxed text-dim">
            Charly answers phones for German municipalities, 24/7, in 30+
            languages. This project rebuilds the speech and orchestration layer
            the way an eval-gated team would: every quality claim has a command
            that reproduces it, and every number this page shows is either that
            output or explicitly marked pending.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {headlineMetrics.map((m) => (
              <div
                key={m.label}
                className="rounded-lg border border-line bg-panel p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] uppercase tracking-wide text-dim">
                    {m.label}
                  </span>
                  <StatusBadge status={m.status} />
                </div>
                <div className="mt-2 font-mono text-2xl text-fg">{m.value}</div>
                {m.command && (
                  <code className="mt-2 block truncate font-mono text-[11px] text-amber">
                    $ {m.command}
                  </code>
                )}
                {m.note && (
                  <p className="mt-1 text-xs text-dim">{m.note}</p>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* ------------------------------------------------ architecture */}
        <section id="architecture" className="space-y-6">
          <h2 className="text-2xl font-semibold">Architecture</h2>
          <p className="max-w-2xl text-dim">
            One pipeline per call, strict layer boundaries, and contracts that
            let providers change without touching orchestration. Hover the
            nodes — each one says why it exists.
          </p>
          <ArchitectureExplorer />
        </section>

        {/* ------------------------------------------------ speech layer */}
        <section id="speech" className="space-y-6">
          <h2 className="text-2xl font-semibold">The speech layer</h2>
          <p className="max-w-2xl text-dim">
            Open models, self-hosted on EU GPUs, chosen from a manifest-driven
            comparison. Evaluation runs on telephony-degraded audio (8 kHz,
            G.711 μ-law, seeded noise) with speaker-group-leakage-safe splits —
            because clean-studio WER is not phone-call WER.
          </p>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[720px] text-left font-mono text-sm">
              <thead>
                <tr className="border-b border-line bg-panel text-[11px] uppercase text-dim">
                  <th className="px-4 py-3">model</th>
                  <th className="px-4 py-3">family</th>
                  <th className="px-4 py-3">params</th>
                  <th className="px-4 py-3">German</th>
                  <th className="px-4 py-3">license</th>
                  <th className="px-4 py-3">telephony WER</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {speechModels.map((row) => (
                  <tr key={row.model}>
                    <td className="px-4 py-3 text-fg">{row.model}</td>
                    <td className="px-4 py-3 text-dim">{row.family}</td>
                    <td className="px-4 py-3 text-dim">{row.params}</td>
                    <td className="px-4 py-3 text-dim">{row.german}</td>
                    <td className="px-4 py-3 text-dim">{row.license}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={row.status} />{" "}
                      <span className="text-[11px] text-dim">
                        {row.werTelephony}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <BenchmarkDownload />
        </section>

        {/* ------------------------------------------------ demo replay */}
        <section id="demo" className="space-y-6">
          <h2 className="text-2xl font-semibold">One call, every hard case</h2>
          <p className="max-w-2xl text-dim">
            This is the repo&apos;s own acceptance scenario — a scripted citizen
            call that exercises correction, retrieval grounding, a typed
            idempotent tool, dictated numbers, and barge-in. It is the same
            scenario the CI gate runs.
          </p>
          <LiveDemo />
        </section>

        {/* ------------------------------------------------ load */}
        <section id="load" className="space-y-6">
          <h2 className="text-2xl font-semibold">Load & admission control</h2>
          <p className="max-w-2xl text-dim">
            The first line of defense for 1,000 concurrent calls is refusing
            the 1,001st fast — before any provider token is spent. Measured on
            this machine with 200 requests against a 50-slot admission limit:
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-line bg-panel p-4">
              <div className="font-mono text-[11px] uppercase text-dim">
                admitted / rejected
              </div>
              <div className="mt-2 font-mono text-2xl text-fg">
                {loadResult.admitted} / {loadResult.rejected}
              </div>
              <div className="font-mono text-xs text-dim">
                of {loadResult.requested} requested
              </div>
            </div>
            <div className="rounded-lg border border-line bg-panel p-4">
              <div className="font-mono text-[11px] uppercase text-dim">
                turn latency p50 / p95
              </div>
              <div className="mt-2 font-mono text-2xl text-fg">
                {loadResult.p50Ms} / {loadResult.p95Ms} ms
              </div>
              <div className="font-mono text-xs text-dim">
                orchestration only, fake providers
              </div>
            </div>
            <div className="rounded-lg border border-line bg-panel p-4">
              <div className="font-mono text-[11px] uppercase text-dim">
                wall time, 250 turns
              </div>
              <div className="mt-2 font-mono text-2xl text-fg">
                {loadResult.wallTimeS} s
              </div>
              <div className="font-mono text-xs text-dim">0 errors recorded</div>
            </div>
          </div>
          <div className="rounded-lg border border-line bg-panel p-4">
            <div className="mb-2 font-mono text-[11px] uppercase text-dim">
              debugging runbook — first check per symptom
            </div>
            <ul className="space-y-1.5 font-mono text-xs">
              {runbookExcerpt.map((r) => (
                <li key={r.symptom} className="flex gap-3">
                  <span className="w-56 shrink-0 text-amber">{r.symptom}</span>
                  <span className="text-dim">{r.firstCheck}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ------------------------------------------------ honest limits */}
        <section id="limits" className="space-y-6">
          <h2 className="text-2xl font-semibold">What is not claimed</h2>
          <ul className="max-w-2xl list-disc space-y-3 pl-5 text-dim">
            {honestLimitations.map((item) => (
              <li key={item.slice(0, 40)}>{item}</li>
            ))}
          </ul>
        </section>

        <footer className="border-t border-line pt-8">
          <p className="font-mono text-xs text-dim">
            Static presentation mode — no S3, no PostgreSQL, no provider keys,
            no live inference. Analytics collect engagement events only, no
            PII.
          </p>
          <ContactLink />
        </footer>
      </main>
    </div>
  );
}
