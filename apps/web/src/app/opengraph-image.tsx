import { ImageResponse } from "next/og";

export const alt = "voiceai: a phone agent you can call right now";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const PAD = 72;
const W = size.width - PAD * 2;

// The noisy section sits near the right: a flat pen line with a short jagged run.
const noisy: string[] = [];
for (let x = 760; x <= 960; x += 8) {
  const amp = 6 + 14 * Math.abs(Math.sin(x * 0.37));
  noisy.push(`${x},${x % 16 === 0 ? 20 - amp : 20 + amp}`);
}
const trace = `0,20 760,20 ${noisy.join(" ")} 960,20 ${W},20`;

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#ECEEE8",
          color: "#121513",
          padding: PAD,
        }}
      >
        <div style={{ display: "flex", fontSize: 26, color: "#4F5550", letterSpacing: 1 }}>
          voiceai · case study by Dibbayajyoti Roy
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 104,
            fontWeight: 700,
            lineHeight: 1,
            letterSpacing: -3,
            maxWidth: 1000,
          }}
        >
          A phone agent you can call right now.
        </div>
        <svg width={W} height={40} viewBox={`0 0 ${W} 40`}>
          <polyline points={trace} fill="none" stroke="#C8321C" strokeWidth={3} />
        </svg>
      </div>
    ),
    { ...size },
  );
}
