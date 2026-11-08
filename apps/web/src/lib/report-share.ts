import { cacheLife } from "next/cache";
import type { CallReportData } from "@/lib/report";

/** Shared report by id, cached for an hour. Server-only callers (share page, metadata, OG image). */
export async function getSharedReport(id: string): Promise<CallReportData | null> {
  "use cache";
  cacheLife({ revalidate: 3600 });
  const control = process.env.NEXT_PUBLIC_DEMO_CONTROL_URL?.replace(/\/+$/, "");
  // Validate before building the URL: the id is user input.
  if (!control || !/^[0-9a-f]{32}$/.test(id)) return null;
  try {
    const res = await fetch(`${control}/report/${id}`);
    return res.ok ? ((await res.json()) as CallReportData) : null;
  } catch {
    return null;
  }
}
