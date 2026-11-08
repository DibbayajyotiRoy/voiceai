import { ContactLink } from "@/components/ContactLink";
import { LiveDemo } from "@/components/LiveDemo";

const GITHUB = "https://github.com/DibbayajyotiRoy/voiceai";

export default function Page() {
  return (
    <main id="main" className="wrap flex min-h-svh flex-col gap-6 py-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <p className="text-lg font-semibold tracking-tight">voiceai</p>
          <p className="phase">by Dibbayajyoti Roy</p>
        </div>
        <nav aria-label="Links" className="flex items-center gap-1 text-sm">
          <a
            href={GITHUB}
            target="_blank"
            rel="noopener noreferrer"
            className="trace-link inline-flex min-h-11 items-center px-2"
          >
            GitHub
          </a>
          <ContactLink />
        </nav>
      </header>

      <div className="flex flex-1 flex-col items-center justify-center gap-10 text-center">
        <div className="max-w-[44ch] space-y-3">
          <h1 className="text-[length:var(--t-l)] font-semibold leading-tight tracking-tight">
            Talk to a voice agent.
          </h1>
          <p className="text-muted">
            It explains what this open voice-agent stack is for, where it fits, and how it
            works. Tap the orb to call.
          </p>
        </div>
        <LiveDemo />
      </div>

      <p className="mono mx-auto max-w-[72ch] text-center text-xs text-muted">
        Runs on AWS Bedrock Nova 2 Sonic over WebRTC. The page loads no S3, no PostgreSQL and no
        provider keys; calls are capped at five minutes.
      </p>
    </main>
  );
}
