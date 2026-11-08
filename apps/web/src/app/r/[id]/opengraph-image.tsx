import { ImageResponse } from "next/og";
import { fmtDuration, fmtSec } from "@/lib/report";
import { getSharedReport } from "@/lib/report-share";

export const alt = "A live voice AI call: median reply and turns";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await getSharedReport(id);
  const p50 = r?.latency_ms?.p50;
  const median = p50 == null ? "—" : fmtSec(p50);

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          width: "100%",
          height: "100%",
          padding: "64px 72px",
          background: "#121513",
          color: "#ECEEE8",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontSize: 30, color: "#A3AAA4" }}>
          <div style={{ display: "flex", width: 16, height: 16, borderRadius: 8, background: "#e879c6" }} />
          <div style={{ display: "flex", marginLeft: 16 }}>A live call with the voiceai agent</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 230, fontWeight: 700, lineHeight: 1, letterSpacing: -6 }}>
            {median}
          </div>
          <div style={{ display: "flex", marginTop: 16, fontSize: 44, color: "#e879c6" }}>median reply</div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 28, color: "#A3AAA4" }}>
          <div style={{ display: "flex" }}>
            {r ? `${r.turns} turns · ${fmtDuration(r.duration_s)} call` : "voiceai"}
          </div>
          <div style={{ display: "flex" }}>voiceai · talk to a live voice agent</div>
        </div>
      </div>
    ),
    size,
  );
}
