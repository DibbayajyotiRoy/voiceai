import type { Metadata } from "next";
import type { ReactNode } from "react";

// Static export needs one concrete page per dynamic route. The real share id is read by the
// client component from the browser URL, and public/_redirects rewrites every /r/<id> to this
// shell, so a single placeholder id serves all shared reports.
export function generateStaticParams() {
  return [{ id: "call" }];
}

export const metadata: Metadata = {
  title: "Call report",
  description: "A live call with the voiceai agent: reply times for every turn, measured on the server.",
  robots: { index: false, follow: false },
};

export default function ShareLayout({ children }: { children: ReactNode }) {
  return children;
}
