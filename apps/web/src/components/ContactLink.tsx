"use client";

import { track } from "@vercel/analytics";

export function ContactLink() {
  return (
    <a
      href="mailto:rdibbayajyoti@gmail.com"
      onClick={() => track("contact_link_clicked")}
      className="mt-4 inline-block rounded bg-amber px-5 py-2.5 font-mono text-sm font-semibold text-ink"
    >
      Get in touch →
    </a>
  );
}
