"use client";

import { useState } from "react";
import { architecture, type ArchNode } from "@/lib/data";

const W = 1040;
const H = 220;

/** Interactive architecture map: hover, focus or tap a node, read why it exists. */
export function ArchitectureExplorer() {
  const [active, setActive] = useState<ArchNode>(architecture[1]);

  return (
    <div className="border border-line bg-ground">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="hidden w-full md:block"
        role="group"
        aria-label="System architecture diagram"
      >
        {/* edges */}
        <g style={{ stroke: "var(--line)" }} strokeWidth="1.5" fill="none">
          <path d="M 150 65 L 190 65" />
          <path d="M 360 65 L 400 30" />
          <path d="M 360 65 L 400 105" />
          <path d="M 580 30 L 620 65" />
          <path d="M 580 105 L 620 65" />
          <path d="M 790 65 L 830 65" />
          <path d="M 705 115 L 705 150" />
          <path d="M 790 175 L 830 175" />
        </g>
        {architecture.map((node) => {
          const on = active.id === node.id;
          return (
            <g
              key={node.id}
              role="button"
              tabIndex={0}
              aria-label={node.label}
              aria-pressed={on}
              className="cursor-pointer"
              onMouseEnter={() => setActive(node)}
              onFocus={() => setActive(node)}
              onClick={() => setActive(node)}
            >
              <rect
                x={node.x}
                y={node.y}
                width={node.w}
                height={46}
                rx={0}
                style={{ fill: "var(--ground)", stroke: on ? "var(--pen)" : "var(--muted)" }}
                strokeWidth={on ? 2.5 : 1.5}
              />
              <text
                x={node.x + node.w / 2}
                y={node.y + 28}
                textAnchor="middle"
                fontSize={13}
                style={{
                  fill: on ? "var(--ink)" : "var(--muted)",
                  fontFamily: "var(--font-jetbrains)",
                }}
              >
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Phones: the diagram is too small to read, so the same nodes are buttons (svg hidden below md). */}
      <ul className="grid gap-2 border-t border-line p-3 md:hidden">
        {architecture.map((node) => {
          const on = active.id === node.id;
          return (
            <li key={node.id}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => setActive(node)}
                className={`mono flex min-h-11 w-full items-center justify-between border px-3 text-left text-sm ${
                  on ? "border-pen text-pen" : "border-line text-ink"
                }`}
              >
                {node.label}
                <span className="text-xs text-muted">{node.layer}</span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="border-t border-line px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="mono text-sm font-semibold">{active.label}</span>
          <span className="mono text-xs uppercase text-muted">{active.layer} layer</span>
        </div>
        <p className="mt-2 max-w-3xl text-base text-muted">{active.detail}</p>
      </div>
    </div>
  );
}
