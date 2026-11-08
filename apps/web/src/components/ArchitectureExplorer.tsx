"use client";

import { useState } from "react";
import { architecture, layerColors, type ArchNode } from "@/lib/data";

const W = 1040;
const H = 220;

/** Interactive architecture map: hover a node, read why it exists. */
export function ArchitectureExplorer() {
  const [active, setActive] = useState<ArchNode>(architecture[1]);

  return (
    <div className="rounded-lg border border-line bg-panel">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="System architecture diagram"
      >
        {/* edges */}
        <g stroke="#232a32" strokeWidth="1.5" fill="none">
          <path d="M 150 65 L 190 65" />
          <path d="M 360 65 L 400 30" />
          <path d="M 360 65 L 400 105" />
          <path d="M 580 30 L 620 65" />
          <path d="M 580 105 L 620 65" />
          <path d="M 790 65 L 830 65" />
          <path d="M 705 115 L 705 150" />
          <path d="M 790 175 L 830 175" />
        </g>
        {architecture.map((node) => (
          <g
            key={node.id}
            onMouseEnter={() => setActive(node)}
            className="cursor-pointer"
          >
            <rect
              x={node.x}
              y={node.y}
              width={node.w}
              height={46}
              rx={6}
              fill="#12161b"
              stroke={layerColors[node.layer]}
              strokeWidth={active.id === node.id ? 2.5 : 1}
            />
            <text
              x={node.x + node.w / 2}
              y={node.y + 28}
              textAnchor="middle"
              fill={active.id === node.id ? "#e6e1d8" : "#8a9199"}
              fontSize={13}
              fontFamily="var(--font-geist-mono)"
            >
              {node.label}
            </text>
          </g>
        ))}
      </svg>
      <div className="border-t border-line px-4 py-3">
        <div className="flex items-center gap-3">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ background: layerColors[active.layer] }}
          />
          <span className="font-mono text-sm text-fg">{active.label}</span>
          <span className="font-mono text-[11px] uppercase text-dim">
            {active.layer} layer
          </span>
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-dim">
          {active.detail}
        </p>
      </div>
    </div>
  );
}
