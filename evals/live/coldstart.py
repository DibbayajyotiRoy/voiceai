# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportMissingTypeArgument=false
"""Cold-start measurement v2: robust against the desiredCount/stopped race.

"Genuinely stopped" = control /status says stopped AND the agent health endpoint is
unreachable. A cycle is only valid if startup traverses at least one non-ready stage
(provisioning/pulling/starting) for >=15s; an instant-ready cycle is discarded (the old
task was still draining) and the wait restarts.
"""

import json
import time
import urllib.request

CONTROL = "https://swoeqoivgez5betfuozathcduu0zsrkx.lambda-url.us-east-1.on.aws"
AGENT = "https://demo-api.dibbayajyoti.com/api/demo/idle-seconds"


def control_get(path: str) -> dict:
    with urllib.request.urlopen(f"{CONTROL}{path}", timeout=15) as r:  # noqa: S310
        return json.loads(r.read())


def control_post(path: str) -> dict:
    req = urllib.request.Request(f"{CONTROL}{path}", method="POST", data=b"{}")  # noqa: S310
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        return json.loads(r.read())


def agent_alive() -> bool:
    try:
        with urllib.request.urlopen(AGENT, timeout=8) as r:  # noqa: S310
            r.read()
        return True
    except Exception:
        return False


def genuinely_stopped() -> bool:
    return control_get("/status")["state"] == "stopped" and not agent_alive()


def wait_for_genuine_stopped(timeout_s: float = 3600.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if genuinely_stopped():
            # double-check after 10s to avoid a drain-window false positive
            time.sleep(10)
            if genuinely_stopped():
                return
        time.sleep(20)
    raise TimeoutError("never genuinely stopped")


cycles = []
attempts = 0
while len(cycles) < 3 and attempts < 6:
    attempts += 1
    print(
        f"[{time.strftime('%H:%M:%S')}] cycle-attempt {attempts}: waiting for stopped...",
        flush=True,
    )
    wait_for_genuine_stopped()
    t_wake = time.time()
    control_post("/start")
    stages = []
    last_stage = None
    t_stage = t_wake
    t_first_ready = None
    while True:
        s = control_get("/status")
        stage = s.get("stage", "?")
        if stage != last_stage:
            now = time.time()
            if last_stage is not None:
                stages.append({"stage": last_stage, "dur_s": round(now - t_stage, 1)})
            t_stage = now
            last_stage = stage
            print(
                f"  [{time.strftime('%H:%M:%S')}] stage {stage} at {now - t_wake:.1f}s", flush=True
            )
        if s["stage"] == "ready":
            total = time.time() - t_wake
            if total < 15:
                print(
                    f"  INVALID: ready in {total:.1f}s (old task still draining); discarding",
                    flush=True,
                )
                break
            cycles.append({"cycle": len(cycles) + 1, "stages": stages, "total_s": round(total, 1)})
            print(f"  READY total {total:.1f}s (valid cycle {len(cycles)})", flush=True)
            break
        time.sleep(2)

with open("evals/live/data/coldstart.json", "w") as f:
    json.dump({"attempts": attempts, "cycles": cycles}, f, indent=2)
print("DONE", flush=True)
