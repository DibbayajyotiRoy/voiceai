import type { Metadata, Viewport } from "next";
import { Archivo, JetBrains_Mono } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  axes: ["wdth"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
});

const title = "voiceai: talk to a voice agent";
const description =
  "Talk to an open voice-agent stack running live on AWS Bedrock Nova 2 Sonic. Tap the orb to call.";
const ogImage = {
  url: "/og-image.png",
  width: 1200,
  height: 630,
  alt: "voiceai: a pink particle orb beside the headline Talk to a voice agent",
  type: "image/png",
};

export const metadata: Metadata = {
  metadataBase: new URL("https://voiceai-presentation.vercel.app"),
  title,
  description,
  alternates: { canonical: "/" },
  openGraph: {
    title,
    description,
    url: "/",
    siteName: "voiceai",
    locale: "en_US",
    type: "website",
    images: [ogImage],
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
    creator: "@dibbayajyoti",
    images: [ogImage],
  },
  appleWebApp: {
    title: "voiceai",
    statusBarStyle: "black-translucent",
    capable: true,
  },
};

export const viewport: Viewport = {
  themeColor: "#121513",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${jetbrains.variable} booth h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* Motion is opt-in: no JS or reduced motion means everything is visible. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "if(!matchMedia('(prefers-reduced-motion: reduce)').matches)document.documentElement.classList.add('motion')",
          }}
        />
      </head>
      <body className="min-h-full">
        <a href="#main" className="skip">
          Skip to content
        </a>
        {children}
        {/* Analytics load after hydration and collect no PII (bundle-defer-third-party) */}
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
