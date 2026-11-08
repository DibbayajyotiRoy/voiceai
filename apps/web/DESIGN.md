# DESIGN.md: voiceai presentation

## Brief
- Subject: an open, eval-gated voice agent (German municipal phone use case), built by Dibbayajyoti Roy.
- Audience: recruiters and hiring engineers. Job: in 3 seconds know what this is, in 30 seconds talk to it, in 3 minutes trust the engineering.
- Constraints: every number is MEASURED (with its command) or PENDING. Verify scripts must keep passing
  (strings: "German municipal voice AI", "Architecture", "Speech layer", "MEASURED", "PENDING",
  "no S3, no PostgreSQL", "replay call", 6 analytics events).

## Concepts
| | Idea | Anchor | Signature | O/F/Fe/P |
|---|---|---|---|---|
| A. Material | The page is one phone call: sections follow the agent's real call phases, and a corner state machine fills its slots as you read | `CallPhase` + `SlotStatus` enums in packages/contracts/state.py | the line: one signal trace that idles as line noise and becomes your real voice when you call | 4 / 5 / 4 / 1 |
| B. Formal | Two states only: everything is measured (solid) or pending (hollow) | the repo's honesty rule | claims sort themselves as you scroll | 4 / 4 / 4 / 2 |
| C. Place | Bürgeramt waiting-number display; fast busy as a queue ticket | German municipal offices | ticket counter in the corner | 3 / 3 / 4 / 3 |

Pick A: only this project has these phases and slots, and it puts the live call at the center.
Steal from B: measured numerals are solid ink, pending numerals are hollow outlines.

## Concept card
```
Idea:        This page is a call. Scroll moves it through the agent's real phases; press call and the line is your voice.
Metaphor:    a call trace on chart-recorder paper (the agent's per-call flight recorder)
Signature:   "the line": one canvas trace across the hero and the booth. Idle = faint line noise,
             scroll = the pen speeds with scroll velocity, live call = real mic + agent audio amplitude.
Emotion:     calm control-room confidence; nothing hidden.
Motion verb: trace (things are written left to right by a pen, like a recorder)
Screenshot:  the hero headline with the red trace running under it and the corner state machine reading "phase discovery · slots 0/4"
```

## Phase map (real enum order)
discovery = hero + booth · collecting = evidence + speech layer · confirming = honest limits ·
executing = architecture + load · completed = footer · handoff = contact (handoff to a human).
Slots: demo, evidence, limits, architecture. missing → provisional (in view) → confirmed (passed).

## System
- Palette: ground `#ECEEE8` (recorder paper) · ink `#121513` · muted `#4F5550` (AA on ground) ·
  line `#C5CABF` · accent/pen `#C8321C` (trace, focus ring, primary fill; used sparingly) ·
  booth `#121513` with ink-on-dark `#ECEEE8`, muted-on-dark `#A3AAA4`.
- Type: Archivo variable (wdth 62 to 125, wght) for everything readable; display at wdth 112,
  wght 760, tracking -0.035em; JetBrains Mono for timestamps, phase names, commands.
- Grid: 12 cols, gutter clamp(16px, 2.2vw, 32px). Left 3 cols hold each section's phase label like a trace gutter.
- Shape: radius 0 for panels, 999px only for the call button (a handset key).
- Motion: one ease `cubic-bezier(.16,1,.3,1)`; reveals = clip-path wipe left to right 0.9s;
  hovers = underline traced left to right; buttons flood with pen red from the left; arrows travel.
- Composition: hero = poster; booth = full-bleed dark; evidence = data/facts; speech = index list;
  limits = statement; architecture = diagram; load = big numerals sentence; footer = finale.

## Decisions / deviations
- No Lenis: native scroll keeps the booth's audio UI and keyboard use predictable. One clock: gsap.ticker.
- No loader: the hero is HTML text; the line starts drawing on the first frame.
- Single page + designed 404 ("the number you dialled is not in service"); the content is one story, so no case pages.
- Genericness test: dark + amber (old site) is AI tell #2, replaced by recorder paper + pen red.
