# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportOptionalMemberAccess=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportPrivateUsage=false
"""Cold-start measurement: wait for stopped, wake 3 times, log stage durations."""

import json
import time
import urllib.request

CONTROL = "https://swoeqoivgez5betfuozathcduu0zsrkx.lambda-url.us-east-1.on.aws"


def get(path: str) -> dict:  # noqa: S310
    with urllib.request.urlopen(f"{CONTROL}{path}", timeout=15) as r:  # noqa: S310
        return json.loads(r.read())


def post(path: str) -> dict:  # noqa: S310
    req = urllib.request.Request(f"{CONTROL}{path}", method="POST", data=b"{}")  # noqa: S310
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        return json.loads(r.read())


def wait_for_stopped(timeout_s: float = 2400.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        s = get("/status")
        if s["state"] == "stopped":
            return
        time.sleep(20)
    raise TimeoutError("never stopped")


cycles = []
for i in range(3):
    print(f"cycle {i + 1}: waiting for stopped...", flush=True)
    wait_for_stopped()
    t_wake = time.time()
    post("/start")
    stages = []
    last_stage = None
    t_stage = t_wake
    while True:
        s = get("/status")
        stage = s.get("stage", "?")
        if stage != last_stage:
            now = time.time()
            if last_stage is not None:
                stages.append({"stage": last_stage, "dur_s": round(now - t_stage, 1)})
            t_stage = now
            last_stage = stage
            print(f"  cycle {i + 1} stage {stage} at {now - t_wake:.1f}s", flush=True)
        if s["stage"] == "ready":
            total = time.time() - t_wake
            cycles.append({"cycle": i + 1, "stages": stages, "total_s": round(total, 1)})
            print(f"  cycle {i + 1} READY total {total:.1f}s", flush=True)
            break
        time.sleep(2)

with open("evals/live/data/coldstart.json", "w") as f:
    json.dump(cycles, f, indent=2)
print("DONE", flush=True)
