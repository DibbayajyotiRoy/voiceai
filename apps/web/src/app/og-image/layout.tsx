import type { Metadata } from "next";
import type { ReactNode } from "react";

// Capture page for the social card: never indexed, not in sitemap.ts.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function OgImageLayout({ children }: { children: ReactNode }) {
  return children;
}
