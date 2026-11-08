# Hosted presentation and analytics

## Goal

The Vercel site is a self-guided engineering presentation for the Charly application. It demonstrates decisions and evidence without exposing the private voice deployment.

## Demo boundary

- Static/read-only Next.js deployment.
- Sanitized knowledge, scenarios, traces, and benchmark artifacts bundled directly in the site.
- No S3, PostgreSQL, provider keys, administrative actions, or open billable inference.
- Recorded, simulated, real-provider, measured, and target content labeled distinctly.

## Guided narrative

1. Municipal voice problem and constraints.
2. End-to-end architecture and transport boundaries.
3. Pipecat streaming and barge-in.
4. Call state, correction handling, and context engineering.
5. Company knowledge ingestion and hybrid/graph retrieval trade-offs.
6. STT/TTS model selection and fine-tuning.
7. Reproducible evals, cost, and capacity evidence.
8. Injected incident and trace-based debugging.
9. Limitations and a concise map to the job requirements.

The site includes an interactive architecture explorer, synchronized voice/transcript/state/tool replay, an incident waterfall, and downloadable raw result JSON. It works on mobile/desktop, with keyboard access and text alternatives to audio.

## Analytics

Use Vercel Web Analytics and Speed Insights. Track only events that answer whether a visitor engaged with the presentation:

- `presentation_started`
- `demo_replay_started`
- `demo_replay_completed`
- `benchmark_downloaded`
- `presentation_completed`
- `contact_link_clicked`

Properties are limited to safe section or scenario identifiers. No names, email addresses, transcripts, call IDs, or other PII enter analytics. Events must fire once at their defined trigger and be checked on the deployed site.

## Deployment

Live demo-mode deployment: https://voiceai-presentation.vercel.app

- `npm --prefix apps/web run build && node scripts/verify-presentation.mjs` → G4 (passed 2026-11-08)
- `node scripts/verify-deployed-presentation.mjs https://voiceai-presentation.vercel.app` → G5 (passed 2026-11-08)

A tagged application URL can help distinguish an outreach campaign where supported. Anonymous visits, referrers, devices, locations, and engagement do **not** prove that Charly or a particular reviewer visited. Do not attempt covert identification.

Add another analytics provider only if a specific question remains unanswered. Configure any cookie-based tooling with appropriate notice/consent and EU privacy settings.
