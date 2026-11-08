"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { gsap } from "gsap";
import { track } from "@vercel/analytics";
import { Orb, type OrbPhase } from "@/components/Orb";
import { signal } from "@/lib/signal";

// Public base URL of the control API. Inlined at build time; unset = calls off.
const CONTROL_URL = process.env.NEXT_PUBLIC_DEMO_CONTROL_URL?.replace(/\/+$/, "");
const POLL_MS = 3000;
const WAKE_TIMEOUT_MS = 150_000;
const ICE_WAIT_MS = 3000;
const MAX_CALL_S = 300;

type Backend = { state: "stopped" | "starting" | "ready"; url: string | null };
type Phase = OrbPhase;

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

/** The orb: one click starts a WebRTC call with the scale-to-zero AWS agent, one click ends it. */
export function LiveDemo() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const sessionRef = useRef<Session | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");

  // Page load: count the visit, then wake the agent so it is often ready before the first click.
  useEffect(() => {
    track("presentation_started");
    if (CONTROL_URL) {
      fetchBackend("start").catch(() => {
        // Ignored: clicking the orb retries and reports errors.
      });
    }
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
    if (s) {
      if (s.live) track("call_ended");
      teardown(s);
    }
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

    // Live: reset the session timer and drive the orb from mic and agent audio.
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
            "The agent did not wake up in time. Try again later.",
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
  const orbLabel = !CONTROL_URL
    ? "Live calls are off"
    : phase === "live"
      ? "End call"
      : busy
        ? "Cancel"
        : "Start call";
  const onOrb = () => (busy || phase === "live" ? hangUp() : startCall());

  // The clock ticks every second; it is aria-hidden so the live region does not chatter.
  let status: ReactNode;
  if (!CONTROL_URL) {
    status = "Live calls are off in this build.";
  } else if (phase === "idle") {
    status = `${message ? `${message} ` : ""}Tap to call.`;
  } else if (phase === "waking") {
    status = (
      <>
        Waking the agent on AWS. First call takes up to two minutes; it sleeps when unused.{" "}
        <span aria-hidden="true">({elapsed}s)</span>
      </>
    );
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
    <div className="flex flex-col items-center gap-6">
      <Orb phase={phase} enabled={!!CONTROL_URL} label={orbLabel} onClick={onOrb} />
      <p role="status" aria-live="polite" className="mono min-h-[3rem] max-w-[52ch] text-center text-sm text-muted">
        {status}
      </p>
      {/* Remote agent audio; autoplay is triggered from a user gesture. */}
      <audio ref={audioRef} autoPlay />
    </div>
  );
}
