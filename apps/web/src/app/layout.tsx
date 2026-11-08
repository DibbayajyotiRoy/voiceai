import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Charly-style Voice AI — Engineering Case Study",
  description:
    "How a German municipal voice agent is built: eval-gated speech layer, typed call state machine, Pipecat pipelines, honest benchmarks.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-[#0b0e11] text-[#e6e1d8]">
        {children}
        {/* Analytics load after hydration and collect no PII (bundle-defer-third-party) */}
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
