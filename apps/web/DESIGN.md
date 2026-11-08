# DESIGN.md: voiceai

## Brief
One full-viewport dark screen. A headline, one glowing pen-red orb in the center, and a status line under it. Tap the orb to call the open voice agent (AWS Bedrock Nova 2 Sonic over WebRTC); the agent greets first. The orb is the only control and the only picture: idle it breathes slowly, waking and connecting it sends a slow ring out, live its surface moves with the real mic and agent audio. Nothing else competes with it. The status line carries every state in text, and reduced motion keeps a still sphere with the same text.

Constraints: the page loads no S3, no PostgreSQL and no provider keys (bundle scan, verified). Analytics events: presentation_started, call_started, call_ended, contact_link_clicked.

## System
- Palette: ground `#ECEEE8` (recorder paper) · ink `#121513` · muted `#4F5550` (AA on ground) ·
  line `#C5CABF` · accent/pen `#C8321C` (orb, focus ring, primary fill; used sparingly) ·
  booth `#121513` with ink-on-dark `#ECEEE8`, muted-on-dark `#A3AAA4`. The page is the booth (dark) scope on `<html>`.
- Type: Archivo variable (wdth 62 to 125, wght) for everything readable; display at wdth 112,
  wght 760, tracking -0.035em; JetBrains Mono for the status line, timestamps and commands.
- Shape: radius 0 for panels, 999px for the orb and the handset key.
- Motion: one ease `cubic-bezier(.16,1,.3,1)` for CSS; the orb runs on gsap.ticker only (one clock).
- Layout: wrap column, gutter clamp(16px, 2.2vw, 32px); no horizontal overflow at any width (`overflow-x: clip`).

## Decisions / deviations
- One screen, no sections, no replay, no architecture or evidence panels: the call is the page.
- No loader: the headline is HTML text; the orb draws on the first frame.
- Designed 404 ("the number you dialled is not in service") reuses the signal line and links back to the agent.
