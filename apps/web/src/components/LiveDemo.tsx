"use client";

import { useEffect, useRef, useState } from "react";
import { DemoReplay } from "@/components/DemoReplay";

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
};

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

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
  s.pc?.close();
  s.stream?.getTracks().forEach((t) => t.stop());
  void s.audioCtx?.close();
}

const fmt = (s: number) =>
  `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

const buttonClass =
  "rounded bg-amber px-3 py-1 font-mono text-xs font-semibold text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber";
const ghostButtonClass =
  "rounded border border-line px-3 py-1 font-mono text-xs text-fg hover:border-amber focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber";

/** Live WebRTC voice demo backed by the scale-to-zero AWS agent, with the replay as fallback. */
export function LiveDemo() {
  const rootRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const meterRef = useRef<HTMLDivElement>(null);
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
      a.srcObject = e.streams[0] ?? new MediaStream([e.track]);
      void a.play().catch(() => {
        // Autoplay blocked: the user can still press play on the control.
      });
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

    // Live: reset the session timer and start the mic level meter.
    s.live = true;
    s.t0 = Date.now();
    const ctx = new AudioContext();
    s.audioCtx = ctx;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    s.timers.push(
      window.setInterval(() => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += ((v - 128) / 128) ** 2;
        const level = Math.min(1, Math.sqrt(sum / buf.length) * 4);
        if (meterRef.current) meterRef.current.style.transform = `scaleX(${level})`;
      }, 100),
    );
    setElapsed(0);
    setPhase("live");
  };

  const startCall = async () => {
    if (!CONTROL_URL || sessionRef.current) return;
    const s: Session = { cancelled: false, live: false, t0: Date.now(), timers: [] };
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
          throw new Error("The agent did not wake up in time. Try again later, or listen to the replay.");
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

  if (!CONTROL_URL) return <DemoReplay />;

  const busy = phase === "waking" || phase === "connecting";
  const statusText =
    phase === "idle"
      ? message ||
        "Talk to the agent live. It runs on AWS and scales to zero when unused to save cost, so the first start takes about a minute."
      : phase === "waking"
        ? `Waking the agent on AWS — about a minute, it scales to zero when unused to save cost. (${elapsed}s)`
        : phase === "connecting"
          ? "Agent is awake. Connecting audio…"
          : phase === "live"
            ? `Live — you are talking to the agent. ${fmt(elapsed)} of 05:00.`
            : message;

  return (
    <div ref={rootRef} className="space-y-4">
      <div className="rounded-lg border border-line bg-panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h3 className="font-mono text-xs text-fg">talk to the live demo</h3>
          <div className="flex items-center gap-2">
            {(phase === "idle" || phase === "error") && (
              <button onClick={startCall} className={buttonClass}>
                {phase === "error" ? "Try again" : "Start"}
              </button>
            )}
            {busy && (
              <button onClick={hangUp} className={ghostButtonClass}>
                Cancel
              </button>
            )}
            {phase === "live" && (
              <button onClick={hangUp} className={buttonClass}>
                End call
              </button>
            )}
          </div>
        </div>
        <div className="space-y-4 p-4">
          <p role="status" aria-live="polite" className="font-mono text-sm text-dim">
            {statusText}
          </p>
          {phase === "live" && (
            <div className="space-y-2">
              <div className="flex items-center justify-between font-mono text-[11px] uppercase tracking-wider text-dim">
                <span>microphone level</span>
                <span>{fmt(elapsed)} / 05:00</span>
              </div>
              <div
                aria-hidden="true"
                className="h-2 w-full overflow-hidden rounded-sm bg-line"
              >
                <div
                  ref={meterRef}
                  className="h-full origin-left bg-pass"
                  style={{ transform: "scaleX(0)" }}
                />
              </div>
            </div>
          )}
          {phase === "error" && (
            <p className="font-mono text-xs text-dim">
              The recorded call below works offline.
            </p>
          )}
          {/* Remote agent audio; autoplay is triggered from a user gesture. */}
          <audio ref={audioRef} autoPlay />
        </div>
      </div>
      <DemoReplay />
    </div>
  );
}
