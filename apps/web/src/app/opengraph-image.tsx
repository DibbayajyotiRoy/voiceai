import { ImageResponse } from "next/og";

export const alt = "voiceai: talk to a voice agent";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const PAD = 72;

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "#121513",
          color: "#ECEEE8",
          padding: PAD,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ display: "flex", fontSize: 26, color: "#A3AAA4", letterSpacing: 1 }}>
            voiceai · by Dibbayajyoti Roy
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 96,
              fontWeight: 700,
              lineHeight: 1,
              letterSpacing: -3,
              maxWidth: 680,
            }}
          >
            Talk to a voice agent.
          </div>
        </div>
        <div
          style={{
            display: "flex",
            width: 380,
            height: 380,
            borderRadius: 190,
            background:
              "radial-gradient(circle at 36% 32%, #ff9a85 0%, #ff5a3d 45%, #8f2514 100%)",
            boxShadow: "0 0 90px 20px rgba(255, 90, 61, 0.35)",
          }}
        />
      </div>
    ),
    { ...size },
  );
}
