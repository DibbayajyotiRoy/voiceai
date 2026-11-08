"use client";

import { useEffect } from "react";
import { trackEvent } from "@/lib/track";

/** Counts a shared report view once per mount. Renders nothing. */
export function ReportOpened({ shareId }: { shareId: string }) {
  useEffect(() => {
    trackEvent("page_view");
    trackEvent("report_opened", { share_id: shareId });
  }, [shareId]);
  return null;
}
