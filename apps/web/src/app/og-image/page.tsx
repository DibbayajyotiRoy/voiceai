"use client";

import { useEffect } from "react";
import Script from "next/script";

// Dev overlays must not appear in the 1200x630 capture.
const HIDE_DEV = `[data-nextjs-dialog-overlay],[data-nextjs-dialog],nextjs-portal,#__next-build-indicator{display:none!important}
html,body{margin:0;overflow:hidden}`;

const MONO = "var(--font-jetbrains), ui-monospace, monospace";
const SANS = "var(--font-archivo), system-ui, sans-serif";

/** Static OG card, screenshotted by playwright into public/og-image.png. Not linked anywhere. */
export default function OgImage() {
  // The vendored orb draws a ring per syllable only when its voice envelope rises.
  // No call is running here, so a steady pulse stands in for speech (screenshot only).
  useEffect(() => {
    const orb = document.querySelector<HTMLElement & { envFn?: () => number }>("speaking-orb");
    if (orb) orb.envFn = () => 0.45 + 0.4 * Math.max(0, Math.sin(performance.now() / 160));
  }, []);

  return (
    <main
      style={{
        position: "relative",
        width: 1200,
        height: 630,
        overflow: "hidden",
        display: "flex",
        background: "#121513",
        color: "#ECEEE8",
        fontFamily: SANS,
      }}
    >
      <style>{HIDE_DEV}</style>
      <Script src="/vendor/speaking-orb.js" strategy="afterInteractive" />

      <section
        style={{
          position: "relative",
          zIndex: 1,
          width: "55%",
          padding: "64px 40px 56px 72px",
          boxSizing: "border-box",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 22, letterSpacing: "0.04em" }}>
          voiceai <span style={{ color: "#A3AAA4" }}>· open source</span>
        </p>

        <div>
          <h1
            style={{
              margin: 0,
              fontSize: 92,
              fontWeight: 760,
              lineHeight: 0.92,
              letterSpacing: "-0.035em",
              fontVariationSettings: '"wdth" 100',
            }}
          >
            Talk to a
            <br />
            voice agent.
          </h1>
          <p
            style={{
              margin: "28px 0 0",
              maxWidth: 500,
              fontSize: 26,
              lineHeight: 1.4,
              color: "#A3AAA4",
            }}
          >
            Real-time voice on AWS Bedrock Nova 2 Sonic over WebRTC. Live latency report after every
            call.
          </p>
        </div>

        <div style={{ fontFamily: MONO, fontSize: 20, lineHeight: 1.6 }}>
          <p style={{ margin: 0 }}>voiceai-presentation.vercel.app</p>
          <p style={{ margin: 0, color: "#A3AAA4" }}>by Dibbayajyoti Roy</p>
        </div>
      </section>

      <div
        style={{
          position: "relative",
          width: "45%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            width: 640,
            height: 640,
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(255,150,214,0.30) 0%, rgba(255,150,214,0.10) 36%, rgba(18,21,19,0) 70%)",
          }}
        />
        <speaking-orb
          aria-hidden="true"
          state="speaking"
          level="0.6"
          particles="1400"
          style={{ position: "relative", display: "block", width: 460, height: 460 }}
        />
      </div>
    </main>
  );
}
