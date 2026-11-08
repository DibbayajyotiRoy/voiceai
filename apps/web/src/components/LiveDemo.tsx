"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { gsap } from "gsap";
import { track } from "@vercel/analytics";
import { Orb, type OrbState } from "@/components/Orb";
import { CallReport } from "@/components/CallReport";
import { WakeProgress } from "@/components/WakeProgress";
import { signal } from "@/lib/signal";
import type { CallReportData } from "@/lib/report";

// Public base URL of the control API. Inlined at build time; unset = calls off.
const CONTROL_URL = process.env.NEXT_PUBLIC_DEMO_CONTROL_URL?.replace(/\/+$/, "");
const POLL_MS = 3000;
const WAKE_TIMEOUT_MS = 150_000;
const ICE_WAIT_MS = 3000;
const MAX_CALL_S = 300;
const REPORT_POLL_MS = 1000;
const REPORT_MAX_MS = 15_000;
const TALK_HOLD_FRAMES = 12; // about 200 ms at 60 fps before the orb switches talker

type Backend = {
  state: "stopped" | "starting" | "ready";
  url: string | null;
  stage?: string | null;
  since_s?: number | null;
};
type WakeInfo = { stage: string | null; sinceS: number | null };
type Phase = "idle" | "waking" | "connecting" | "live" | "error";
type Talker = "listening" | "speaking";
type ReportState =
  | { kind: "none" }
  | { kind: "pending" }
  | { kind: "unavailable" }
  | { kind: "ready"; data: CallReportData };

/** One start-to-hangup attempt. Teardown is driven entirely from here. */
type Session = {
  cancelled: boolean;
  live: boolean;
  t0: number;
  timers: number[];
  pc?: RTCPeerConnection;
  stream?: MediaStream;
  audioCtx?: AudioContext;
  mic?: AnalyserNode;
  agentMeters: AnalyserNode[];
  tick?: () => void;
  report?: { base: string; pcId: string };
};

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

const meterBuf = new Float32Array(512);
/** RMS of an analyser's time-domain signal, scaled to 0..1. */
function rms(an: AnalyserNode) {
  an.getFloatTimeDomainData(meterBuf);
  let sum = 0;
  for (const v of meterBuf) sum += v * v;
  return Math.min(1, Math.sqrt(sum / meterBuf.length) * 4);
}

const freqBuf = new Uint8Array(1024);
/** Mean spectral energy (0..1) of an analyser between two frequencies. */
function band(an: AnalyserNode, lo: number, hi: number) {
  const n = an.frequencyBinCount;
  an.getByteFrequencyData(freqBuf.subarray(0, n));
  const hz = an.context.sampleRate / 2 / n;
  const a = Math.max(1, Math.floor(lo / hz));
  const b = Math.min(n - 1, Math.ceil(hi / hz));
  let sum = 0;
  for (let i = a; i <= b; i++) sum += freqBuf[i];
  return sum / ((b - a + 1) * 255);
}

async function fetchBackend(action: "start" | "status"): Promise<Backend> {
  const res = await fetch(`${CONTROL_URL}/${action}`, {
    method: action === "start" ? "POST" : "GET",
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Control API returned HTTP ${res.status}.`);
  return res.json();
}

const wakeFrom = (b: Backend): WakeInfo => ({
  stage: b.stage ?? null,
  sinceS: typeof b.since_s === "number" ? b.since_s : null,
});

function waitForIce(pc: RTCPeerConnection, maxMs: number) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise<void>((resolve) => {
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", check);
      clearTimeout(timer);
      resolve();
    };
    const check = () => {
      if (pc.iceGatheringState === "complete") done();
    };
    const timer = setTimeout(done, maxMs);
    pc.addEventListener("icegatheringstatechange", check);
  });
}

function teardown(s: Session) {
  s.cancelled = true;
  s.timers.forEach((t) => clearInterval(t));
  if (s.tick) gsap.ticker.remove(s.tick);
  signal.level = 0;
  signal.mic = 0;
  signal.agent = 0;
  signal.voice = 0;
  signal.hiss = 0;
  signal.live = false;
  s.pc?.close();
  s.stream?.getTracks().forEach((t) => t.stop());
  void s.audioCtx?.close();
}

const fmt = (s: number) =>
  `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

/** The orb: one click starts a WebRTC call with the scale-to-zero AWS agent, one click ends it. */
export function LiveDemo() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const orbRef = useRef<HTMLButtonElement>(null);
  const sessionRef = useRef<Session | null>(null);
  const reportRun = useRef(0); // bumped to cancel an in-flight report poll
  const [phase, setPhase] = useState<Phase>("idle");
  const [talker, setTalker] = useState<Talker>("listening");
  const [ended, setEnded] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");
  const [reportState, setReportState] = useState<ReportState>({ kind: "none" });
  const [wake, setWake] = useState<WakeInfo>({ stage: null, sinceS: null });

  // Page load: count the visit, then wake the agent so it is often ready before the first click.
  useEffect(() => {
    track("presentation_started");
    if (CONTROL_URL) {
      fetchBackend("start")
        .then((b) => setWake(wakeFrom(b)))
        .catch(() => {
          // Ignored: clicking the orb retries and reports errors.
        });
    }
  }, []);

  // Stop everything if the page unmounts mid-call or mid-report.
  useEffect(() => {
    const runs = reportRun;
    return () => {
      runs.current++;
      const s = sessionRef.current;
      sessionRef.current = null;
      if (s) teardown(s);
    };
  }, []);

  /** Poll the server report until it is ready (202 = not yet), for up to REPORT_MAX_MS. */
  const startReport = async (base: string, pcId: string) => {
    const run = ++reportRun.current;
    const alive = () => run === reportRun.current;
    setReportState({ kind: "pending" });
    const t0 = Date.now();
    while (Date.now() - t0 < REPORT_MAX_MS) {
      const res = await fetch(`${base}/api/demo/report/${encodeURIComponent(pcId)}`, {
        cache: "no-store",
      }).catch(() => null);
      if (!alive()) return;
      // 202 is also "ok" but its body is {"status":"live"}, not a report.
      if (res?.status === 200) {
        const data: CallReportData | null = await res.json().catch(() => null);
        if (!alive()) return;
        if (data?.call_id) {
          setReportState({ kind: "ready", data });
          return;
        }
        break;
      }
      if (res && res.status !== 202) break;
      await sleep(REPORT_POLL_MS);
      if (!alive()) return;
    }
    if (alive()) setReportState({ kind: "unavailable" });
  };

  const finish = (next: "idle" | "error", msg: string) => {
    const s = sessionRef.current;
    sessionRef.current = null;
    if (s) {
      if (s.live) track("call_ended");
      teardown(s);
    }
    if (audioRef.current) audioRef.current.srcObject = null;
    setPhase(next);
    setMessage(msg);
    if (s?.live) {
      setEnded(true);
      if (s.report) void startReport(s.report.base, s.report.pcId);
    }
  };

  const connect = async (s: Session, base: string) => {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    s.stream = stream;
    if (s.cancelled) return;

    const pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });
    s.pc = pc;
    pc.ontrack = (e) => {
      const a = audioRef.current;
      if (!a) return;
      const remote = e.streams[0] ?? new MediaStream([e.track]);
      a.srcObject = remote;
      void a.play().catch(() => {
        // Autoplay blocked: the user can still press play on the control.
      });
      // Agent audio feeds the signal through the same AudioContext as the mic.
      if (s.audioCtx) {
        const an = s.audioCtx.createAnalyser();
        an.fftSize = 512;
        s.audioCtx.createMediaStreamSource(remote).connect(an);
        s.agentMeters.push(an);
      }
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed" && sessionRef.current === s) {
        finish("error", "The connection to the agent was lost.");
      }
    };

    // sendrecv transceiver carries the mic out and the agent's audio back.
    pc.addTransceiver(stream.getAudioTracks()[0], { direction: "sendrecv", streams: [stream] });
    await pc.setLocalDescription(await pc.createOffer());
    await waitForIce(pc, ICE_WAIT_MS);
    if (s.cancelled) return;

    const res = await fetch(`${base}/api/offer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp: pc.localDescription?.sdp, type: "offer" }),
    });
    if (res.status === 503) {
      throw new Error("The demo is busy right now. Try again in a minute.");
    }
    if (!res.ok) throw new Error(`The agent rejected the connection (HTTP ${res.status}).`);
    const answer: { sdp: string; pc_id?: string } = await res.json();
    if (s.cancelled) return;
    if (answer.pc_id) s.report = { base, pcId: String(answer.pc_id) };
    await pc.setRemoteDescription({ type: "answer", sdp: answer.sdp });

    // Live: reset the session timer and drive the orb from mic and agent audio separately.
    s.live = true;
    s.t0 = Date.now();
    if (s.audioCtx) {
      const mic = s.audioCtx.createAnalyser();
      mic.fftSize = 512;
      s.audioCtx.createMediaStreamSource(stream).connect(mic);
      s.mic = mic;
    }
    let current: Talker = "listening";
    let cand: Talker | null = null;
    let candFrames = 0;
    s.tick = () => {
      const mic = s.mic ? rms(s.mic) : 0;
      let agent = 0;
      let voice = 0;
      let hiss = 0;
      for (const m of s.agentMeters) {
        agent = Math.max(agent, rms(m));
        // ponytail: gains hand-tuned for Nova's voice; retune if the model or voice changes.
        voice = Math.max(voice, Math.min(1, band(m, 300, 3400) * 2.2));
        hiss = Math.max(hiss, Math.min(1, band(m, 3400, 8000) * 4));
      }
      signal.mic = mic;
      signal.agent = agent;
      signal.voice = voice;
      signal.hiss = hiss;
      signal.level = Math.max(mic, agent);
      signal.live = true;
      // The orb switches talker only after the other side has held the floor briefly.
      const want: Talker = agent > mic ? "speaking" : "listening";
      if (want === current) cand = null;
      else if (want !== cand) {
        cand = want;
        candFrames = 0;
      } else if (++candFrames >= TALK_HOLD_FRAMES) {
        current = want;
        cand = null;
        setTalker(want);
      }
    };
    gsap.ticker.add(s.tick);
    setElapsed(0);
    setTalker("listening");
    setPhase("live");
    track("call_started");
  };

  const startCall = async () => {
    if (!CONTROL_URL || sessionRef.current) return;
    // Created inside the click, so the browser allows audio from the start.
    const s: Session = {
      cancelled: false,
      live: false,
      t0: Date.now(),
      timers: [],
      agentMeters: [],
      audioCtx: new AudioContext(),
    };
    sessionRef.current = s;
    reportRun.current++;
    setReportState({ kind: "none" });
    setEnded(false);
    setPhase("waking");
    setWake({ stage: null, sinceS: null });
    setMessage("");
    setElapsed(0);
    s.timers.push(
      window.setInterval(() => {
        const secs = Math.floor((Date.now() - s.t0) / 1000);
        setElapsed(secs);
        if (s.live && secs >= MAX_CALL_S) {
          finish("idle", "Call ended after the 5:00 limit. Start again to keep talking.");
        }
      }, 1000),
    );

    try {
      let b = await fetchBackend("start");
      setWake(wakeFrom(b));
      while (b.state !== "ready" || !b.url) {
        if (Date.now() - s.t0 > WAKE_TIMEOUT_MS) {
          throw new Error("The agent did not wake up in time. Try again later.");
        }
        await sleep(POLL_MS);
        if (s.cancelled) return;
        b = await fetchBackend("status");
        setWake(wakeFrom(b));
      }
      if (s.cancelled) return;
      setPhase("connecting");
      await connect(s, b.url.replace(/\/+$/, ""));
    } catch (err) {
      if (sessionRef.current !== s) return;
      finish("error", err instanceof Error ? err.message : "Something went wrong.");
    }
  };

  const hangUp = () => finish("idle", "Call ended. Thanks for listening.");

  /** Back to the idle orb; the report goes away. */
  const callAgain = () => {
    reportRun.current++;
    setReportState({ kind: "none" });
    setEnded(false);
    setMessage("");
    orbRef.current?.focus();
  };

  const busy = phase === "waking" || phase === "connecting";
  const orbLabel = !CONTROL_URL
    ? "Live calls are off"
    : phase === "live"
      ? "End call"
      : busy
        ? "Cancel"
        : "Start call";
  const onOrb = () => (busy || phase === "live" ? hangUp() : startCall());

  const orbState: OrbState = !CONTROL_URL
    ? "disabled"
    : phase === "waking"
      ? "waking"
      : phase === "connecting"
        ? "connecting"
        : phase === "live"
          ? talker
          : phase === "error" || ended
            ? "ended"
            : "idle";

  // The clock ticks every second; it is aria-hidden so the live region does not chatter.
  let status: ReactNode;
  if (!CONTROL_URL) {
    status = "Live calls are off in this build.";
  } else if (phase === "idle") {
    status = `${message ? `${message} ` : ""}Tap to call.`;
  } else if (phase === "connecting") {
    status = "Connecting audio…";
  } else if (phase === "live") {
    status = (
      <>
        Live <span aria-hidden="true">{fmt(elapsed)} / 05:00.</span> Tap the orb to hang up.
      </>
    );
  } else {
    status = `${message} Tap to try again.`;
  }

  return (
    <div className="flex w-full flex-col items-center gap-6">
      <Orb
        state={orbState}
        enabled={!!CONTROL_URL}
        label={orbLabel}
        onClick={onOrb}
        buttonRef={orbRef}
      />
      {phase === "waking" ? (
        <WakeProgress stage={wake.stage} sinceS={wake.sinceS} elapsed={elapsed} />
      ) : (
        <p role="status" aria-live="polite" className="mono min-h-[3rem] max-w-[52ch] text-center text-sm text-muted">
          {status}
        </p>
      )}
      {reportState.kind === "pending" && <p className="mono text-sm text-muted">Preparing the call report…</p>}
      {reportState.kind === "unavailable" && (
        <p className="mono max-w-[52ch] text-center text-sm text-muted">
          The call report was not ready in time. The call itself is not affected.
        </p>
      )}
      {reportState.kind === "ready" && <CallReport report={reportState.data} onAgain={callAgain} />}
      {/* Remote agent audio; autoplay is triggered from a user gesture. */}
      <audio ref={audioRef} autoPlay />
    </div>
  );
}
