"use client";

import { useEffect, useRef, useState } from "react";
import { CallReport } from "@/components/CallReport";
import { fmtSec, type CallReportData } from "@/lib/report";
import { trackEvent, type ShareChannel } from "@/lib/track";

/** The post-call report in a native modal dialog: focus trap, Escape, backdrop and focus return come from the platform. */
export function ReportDialog({
  report,
  open,
  onClose,
  onAgain,
}: {
  report: CallReportData;
  open: boolean;
  onClose: () => void;
  onAgain: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    else if (!open && d.open) d.close();
  }, [open]);

  const shareId = report.share_id ?? null;
  const p50 = report.latency_ms?.p50;
  const text =
    p50 == null
      ? "I just talked to a live voice AI agent. Try it:"
      : `I just talked to a live voice AI agent: ${fmtSec(p50)} median reply. Try it:`;
  // Built on the client only: this dialog never renders during prerender.
  const link = (channel: ShareChannel) =>
    `${window.location.origin}/r/${shareId}?utm_source=${channel === "copy" ? "link" : channel}&utm_medium=social&utm_campaign=call_report`;
  const enc = encodeURIComponent;
  const shared = (channel: ShareChannel) => {
    if (shareId) trackEvent("report_shared", { share_id: shareId, channel });
  };

  const copy = () => {
    shared("copy");
    navigator.clipboard
      .writeText(link("copy"))
      .then(() => setCopied(true))
      .catch(() => {});
  };
  const nativeShare = () => {
    shared("native");
    navigator.share({ text, url: link("native") }).catch(() => {
      // Cancelled by the user or unsupported: nothing to show.
    });
  };
  const canNativeShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  return (
    <dialog
      ref={ref}
      aria-labelledby="report-title"
      onClose={onClose}
      onClick={(e) => {
        // Only the backdrop: the padding-free dialog's own box is the click target.
        if (e.target === e.currentTarget) ref.current?.close();
      }}
      className="report-dialog"
    >
      <div className="flex flex-col gap-6 p-6 sm:p-8">
        <div className="flex justify-end">
          <button type="button" className="key" onClick={() => ref.current?.close()}>
            Close
          </button>
        </div>

        <CallReport report={report} onAgain={onAgain} />

        {shareId && (
          <div role="group" aria-label="Share this report" className="flex w-full max-w-[52ch] flex-col gap-3 border-t border-line pt-6">
            <p className="phase">Share this report</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="key" onClick={copy}>
                {copied ? "Copied" : "Copy link"}
              </button>
              <a
                className="key"
                href={`https://x.com/intent/post?text=${enc(text)}&url=${enc(link("x"))}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => shared("x")}
              >
                X
              </a>
              <a
                className="key"
                href={`https://www.linkedin.com/sharing/share-offsite/?url=${enc(link("linkedin"))}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => shared("linkedin")}
              >
                LinkedIn
              </a>
              <a
                className="key"
                href={`https://wa.me/?text=${enc(`${text} ${link("whatsapp")}`)}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => shared("whatsapp")}
              >
                WhatsApp
              </a>
              {canNativeShare && (
                <button type="button" className="key" onClick={nativeShare}>
                  Share…
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </dialog>
  );
}
