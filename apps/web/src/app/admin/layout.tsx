import type { Metadata } from "next";
import type { ReactNode } from "react";

// Not linked from the home page; kept out of search engines.
export const metadata: Metadata = {
  title: "Admin · voiceai",
  robots: { index: false, follow: false, googleBot: { index: false, follow: false } },
};

export default function AdminLayout({ children }: { children: ReactNode }) {
  return children;
}
