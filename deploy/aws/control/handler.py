"""Control plane for the demo Fargate task (Lambda + Function URL + 5-min sweep).

POST /start  -> ECS desiredCount 0 -> 1
GET  /status -> stopped | starting | ready (+ url once https /health answers)
EventBridge  -> stop the task when idle (active == 0 and idle > 15 min) or after 60 min.

DNS: on each new task public IP, upsert the A record via the Vercel REST API.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

import boto3

CLUSTER = os.environ.get("CLUSTER", "voiceai-demo")
SERVICE = os.environ.get("SERVICE", "voiceai-demo")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "demo-api.dibbayajyoti.com")
DNS_ZONE = os.environ.get("DNS_ZONE", "dibbayajyoti.com")
DNS_RECORD = os.environ.get("DNS_RECORD", "demo-api")
VERCEL_SECRET_ID = os.environ.get("VERCEL_SECRET_ID", "voiceai/vercel-token")
VERCEL_TEAM_ID = os.environ.get("VERCEL_TEAM_ID", "")

IDLE_LIMIT_S = 900
MAX_RUNTIME_S = 3600

ecs = boto3.client("ecs")
ec2 = boto3.client("ec2")
sm = boto3.client("secretsmanager")

_token: str | None = None
_last_dns_ip: str | None = None


def _json(code: int, body: dict[str, Any]) -> dict[str, Any]:
    # CORS headers come from the Function URL config; do not add them here.
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _desired() -> int:
    svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
    return int(svc["desiredCount"])


def _set_desired(n: int) -> None:
    ecs.update_service(cluster=CLUSTER, service=SERVICE, desiredCount=n)


def _running_task() -> dict[str, Any] | None:
    """Newest RUNNING/PENDING task with its public IP, or None."""
    arns = ecs.list_tasks(cluster=CLUSTER, serviceName=SERVICE, desiredStatus="RUNNING")["taskArns"]
    if not arns:
        return None
    tasks = ecs.describe_tasks(cluster=CLUSTER, tasks=arns)["tasks"]
    if not tasks:
        return None
    task = max(tasks, key=lambda t: t.get("startedAt") or datetime.min.replace(tzinfo=UTC))
    ip = None
    for att in task.get("attachments", []):
        if att.get("type") != "ElasticNetworkInterface":
            continue
        eni_id = next(
            (d["value"] for d in att["details"] if d["name"] == "networkInterfaceId"), None
        )
        if eni_id:
            eni = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])[
                "NetworkInterfaces"
            ][0]
            ip = eni.get("Association", {}).get("PublicIp")
    return {
        "lastStatus": task["lastStatus"],
        "startedAt": task.get("startedAt"),
        "ip": ip,
    }


def _vercel(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    global _token
    if _token is None:
        _token = sm.get_secret_value(SecretId=VERCEL_SECRET_ID)["SecretString"].strip()
    sep = "&" if "?" in path else "?"
    url = f"https://api.vercel.com{path}"
    if VERCEL_TEAM_ID:
        url += f"{sep}teamId={VERCEL_TEAM_ID}"
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def _ensure_dns(ip: str) -> None:
    """Upsert A record demo-api -> ip (TTL 60). Runs only when the IP changes."""
    global _last_dns_ip
    if ip == _last_dns_ip:
        return
    records = _vercel("GET", f"/v5/domains/{DNS_ZONE}/records?limit=100").get("records", [])
    existing = [r for r in records if r.get("name") == DNS_RECORD and r.get("type") == "A"]
    if existing:
        if existing[0].get("value") != ip:
            _vercel("PATCH", f"/v1/domains/records/{existing[0]['id']}", {"value": ip, "ttl": 60})
    else:
        _vercel(
            "POST",
            f"/v2/domains/{DNS_ZONE}/records",
            {"type": "A", "name": DNS_RECORD, "value": ip, "ttl": 60},
        )
    _last_dns_ip = ip


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(f"https://{PUBLIC_HOST}/health", timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _idle() -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(
            f"https://{PUBLIC_HOST}/api/demo/idle-seconds", timeout=5
        ) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def start() -> dict[str, Any]:
    if _desired() < 1:
        _set_desired(1)
    return status()


def status() -> dict[str, Any]:
    if _desired() == 0:
        return {"state": "stopped", "url": None}
    task = _running_task()
    if task is None or task["ip"] is None:
        return {"state": "starting", "url": None}
    _ensure_dns(task["ip"])
    if task["lastStatus"] == "RUNNING" and _healthy():
        return {"state": "ready", "url": f"https://{PUBLIC_HOST}"}
    return {"state": "starting", "url": None}


def sweep(now: float | None = None) -> dict[str, Any]:
    """Scheduled: stop an idle or over-long task. Never stops a task with an active call."""
    now = time.time() if now is None else now
    if _desired() == 0:
        return {"action": "none", "reason": "stopped"}
    task = _running_task()
    if task and task["startedAt"] and now - task["startedAt"].timestamp() > MAX_RUNTIME_S:
        _set_desired(0)
        return {"action": "stop", "reason": "max-runtime"}
    idle = _idle()
    if idle and idle.get("active", 1) == 0 and idle.get("idle_seconds", 0) > IDLE_LIMIT_S:
        _set_desired(0)
        return {"action": "stop", "reason": "idle"}
    return {"action": "none", "reason": "busy-or-young"}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if "requestContext" not in event:  # EventBridge schedule
        return {"sweep": sweep()}
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "")
    try:
        if method == "POST" and path.endswith("/start"):
            return _json(200, start())
        if method == "GET" and path.endswith("/status"):
            return _json(200, status())
        return _json(404, {"error": "not found"})
    except Exception as exc:  # keep CORS headers on failures too
        print(f"error: {exc!r}")
        return _json(500, {"error": str(exc)})
