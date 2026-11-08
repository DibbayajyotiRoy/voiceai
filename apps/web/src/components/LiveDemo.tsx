"use client";

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { DemoReplay } from "@/components/DemoReplay";
import { SignalLine } from "@/components/SignalLine";
import { signal } from "@/lib/signal";

// Public base URL of the control API. Inlined at build time; unset = replay only.
const CONTROL_URL = process.env.NEXT_PUBLIC_DEMO_CONTROL_URL?.replace(/\/+$/, "");
const POLL_MS = 3000;
const WAKE_TIMEOUT_MS = 150_000;
const ICE_WAIT_MS = 3000;
const MAX_CALL_S = 300;

type Backend = { state: "stopped" | "starting" | "ready"; url: string | null };
type Phase = "idle" | "waking" | "connecting" | "live" | "error";

/** One start-to-hangup attempt. Teardown is driven entirely from here. */
type Session = {
  cancelled: boolean;
  live: boolean;
  t0: number;
  timers: number[];
  pc?: RTCPeerConnection;
  stream?: MediaStream;
  audioCtx?: AudioContext;
  meters: AnalyserNode[];
  tick?: () => void;
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

async function fetchBackend(action: "start" | "status"): Promise<Backend> {
  const res = await fetch(`${CONTROL_URL}/${action}`, {
    method: action === "start" ? "POST" : "GET",
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Control API returned HTTP ${res.status}.`);
  return res.json();
}

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
  signal.live = false;
  s.pc?.close();
  s.stream?.getTracks().forEach((t) => t.stop());
  void s.audioCtx?.close();
}

const fmt = (s: number) =>
  `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

// The call key is big on purpose. Inline: .key's own min-height would win over a utility class.
const callKey = { minHeight: 64, padding: "0 2rem", fontSize: "1.125rem" };

/** Live WebRTC voice demo backed by the scale-to-zero AWS agent, with the replay as fallback. */
export function LiveDemo() {
  const rootRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const sessionRef = useRef<Session | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");

  // Prewarm: wake the backend once, when the section first scrolls into view.
  useEffect(() => {
    const el = rootRef.current;
    if (!CONTROL_URL || !el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        fetchBackend("start").catch(() => {
          // Ignored: clicking Start retries and reports errors.
        });
      },
      { threshold: 0.2 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Stop everything if the page unmounts mid-call.
  useEffect(() => {
    return () => {
      const s = sessionRef.current;
      sessionRef.current = null;
      if (s) teardown(s);
    };
  }, []);

  const finish = (next: "idle" | "error", msg: string) => {
    const s = sessionRef.current;
    sessionRef.current = null;
    if (s) teardown(s);
    if (audioRef.current) audioRef.current.srcObject = null;
    setPhase(next);
    setMessage(msg);
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
      // Agent audio feeds the signal line through the same AudioContext as the mic.
      if (s.audioCtx) {
        const an = s.audioCtx.createAnalyser();
        an.fftSize = 512;
        s.audioCtx.createMediaStreamSource(remote).connect(an);
        s.meters.push(an);
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
    const answer = await res.json();
    if (s.cancelled) return;
    await pc.setRemoteDescription({ type: "answer", sdp: answer.sdp });

    // Live: reset the session timer and drive the signal line from mic and agent audio.
    s.live = true;
    s.t0 = Date.now();
    if (s.audioCtx) {
      const mic = s.audioCtx.createAnalyser();
      mic.fftSize = 512;
      s.audioCtx.createMediaStreamSource(stream).connect(mic);
      s.meters.push(mic);
    }
    s.tick = () => {
      let level = 0;
      for (const m of s.meters) level = Math.max(level, rms(m));
      signal.level = level;
      signal.live = true;
    };
    gsap.ticker.add(s.tick);
    setElapsed(0);
    setPhase("live");
  };

  const startCall = async () => {
    if (!CONTROL_URL || sessionRef.current) return;
    // Created inside the click, so the browser allows audio from the start.
    const s: Session = {
      cancelled: false,
      live: false,
      t0: Date.now(),
      timers: [],
      meters: [],
      audioCtx: new AudioContext(),
    };
    sessionRef.current = s;
    setPhase("waking");
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
      while (b.state !== "ready" || !b.url) {
        if (Date.now() - s.t0 > WAKE_TIMEOUT_MS) {
          throw new Error(
            "The agent did not wake up in time. Try again later, or listen to the replay.",
          );
        }
        await sleep(POLL_MS);
        if (s.cancelled) return;
        b = await fetchBackend("status");
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

  const busy = phase === "waking" || phase === "connecting";
  const statusText = !CONTROL_URL
    ? "Live calls are off in this build. The scripted call below runs offline."
    : phase === "idle"
      ? message ||
        "Talk to the agent live. It runs on AWS and scales to zero when unused to save cost, so the first start takes about a minute."
      : phase === "waking"
        ? `Waking the agent on AWS. This takes about a minute, because it scales to zero when unused. (${elapsed}s)`
        : phase === "connecting"
          ? "Agent is awake. Connecting audio…"
          : phase === "live"
            ? `Live. You are talking to the agent. ${fmt(elapsed)} of 05:00.`
            : message;

  return (
    <div ref={rootRef} className="space-y-10">
      <div className="space-y-8">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-5">
          {CONTROL_URL && (phase === "idle" || phase === "error") && (
            <button onClick={startCall} className="key key--solid" style={callKey}>
              {phase === "error" ? "Try again" : "Call the agent"}
            </button>
          )}
          {CONTROL_URL && busy && (
            <button onClick={hangUp} className="key" style={callKey}>
              Cancel
            </button>
          )}
          {CONTROL_URL && phase === "live" && (
            <button onClick={hangUp} className="key key--solid" style={callKey}>
              End call
            </button>
          )}
          <p role="status" aria-live="polite" className="mono max-w-[48ch] text-sm text-muted">
            {statusText}
          </p>
        </div>
        <SignalLine height={200} />
        {phase === "error" && (
          <p className="mono text-sm text-muted">The recorded call below works offline.</p>
        )}
        {/* Remote agent audio; autoplay is triggered from a user gesture. */}
        <audio ref={audioRef} autoPlay />
      </div>
      <div className="space-y-6 border-t border-line pt-10">
        <h3 className="text-[length:var(--t-m)] font-semibold">Or replay the scripted German call</h3>
        <DemoReplay />
      </div>
    </div>
  );
}
