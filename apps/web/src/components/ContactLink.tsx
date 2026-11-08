"use client";

import { track } from "@vercel/analytics";

export function ContactLink() {
  return (
    <a
      href="mailto:rdibbayajyoti@gmail.com"
      onClick={() => track("contact_link_clicked")}
      className="trace-link inline-flex min-h-11 items-center px-2"
    >
      Email
    </a>
  );
}
