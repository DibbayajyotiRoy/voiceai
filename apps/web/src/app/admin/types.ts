import type { AdminSummary } from "@/lib/report";

/** Admin-only shapes. The shared report.ts types belong to another worker. */

export type ShareChannel = "x" | "linkedin" | "whatsapp" | "copy" | "native";

export type TrafficEventType = "page_view" | "call_started" | "call_completed" | "report_shared" | "report_opened";

export type TrafficPoint = {
  lat: number;
  lon: number;
  type: TrafficEventType;
  city: string | null;
  country: string | null;
};

export type AdminTraffic = {
  page_views: number;
  unique_visitors: number;
  calls_started: number;
  calls_completed: number;
  report_opens: number;
  shares_by_channel: Partial<Record<ShareChannel, number>>;
  utm_sources: { source: string; views: number }[];
  by_country: { country: string; views: number; calls: number; opens: number }[];
  points: TrafficPoint[];
};

/** `traffic` is optional: an older backend omits it. */
export type AdminData = AdminSummary & { traffic?: AdminTraffic | null };
