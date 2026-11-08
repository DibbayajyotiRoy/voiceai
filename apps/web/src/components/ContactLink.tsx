"use client";

import { track } from "@vercel/analytics";

export function ContactLink() {
  return (
    <a
      href="mailto:rdibbayajyoti@gmail.com"
      onClick={() => track("contact_link_clicked")}
      className="key key--solid"
    >
      Email Dibbayajyoti
    </a>
  );
}
