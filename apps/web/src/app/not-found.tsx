import Link from "next/link";
import { SignalLine } from "@/components/SignalLine";

export default function NotFound() {
  return (
    <main id="main" className="wrap flex min-h-svh flex-col justify-center gap-10 py-24">
      <p className="phase">
        <b>handoff</b> failed
      </p>
      <h1 className="display max-w-[16ch]">The number you dialled is not in service.</h1>
      <SignalLine height={120} flat />
      <div>
        <Link href="/#demo" className="key key--solid">
          Call the agent instead <span className="arrow" aria-hidden="true">→</span>
        </Link>
      </div>
    </main>
  );
}
