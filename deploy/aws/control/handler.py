"""Control plane for the demo Fargate task (Lambda + Function URL + 5-min sweep).

POST /start        -> ECS desiredCount 0 -> 1
GET  /status       -> stopped | starting | ready (+ url once https /health answers)
GET  /admin/summary -> superadmin view: backend state, call history, totals, AWS cost.
                       Requires `Authorization: Bearer <voiceai/admin-token>`.
EventBridge  -> stop the task when idle (active == 0 and idle > 15 min) or after 60 min.

DNS: on each new task public IP, upsert the A record via the Vercel REST API.
"""

import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3

CLUSTER = os.environ.get("CLUSTER", "voiceai-demo")
SERVICE = os.environ.get("SERVICE", "voiceai-demo")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "demo-api.dibbayajyoti.com")
DNS_ZONE = os.environ.get("DNS_ZONE", "dibbayajyoti.com")
DNS_RECORD = os.environ.get("DNS_RECORD", "demo-api")
VERCEL_SECRET_ID = os.environ.get("VERCEL_SECRET_ID", "voiceai/vercel-token")
VERCEL_TEAM_ID = os.environ.get("VERCEL_TEAM_ID", "")
ADMIN_TOKEN_SECRET = os.environ.get("ADMIN_TOKEN_SECRET", "voiceai/admin-token")
DEMO_CALLS_TABLE = os.environ.get("DEMO_CALLS_TABLE", "voiceai-demo-calls")

IDLE_LIMIT_S = 900
MAX_RUNTIME_S = 3600
CE_CACHE_S = 6 * 3600  # Cost Explorer charges $0.01 per request

ecs = boto3.client("ecs")
ec2 = boto3.client("ec2")
sm = boto3.client("secretsmanager")
ce = boto3.client("ce")
calls_table = boto3.resource("dynamodb").Table(DEMO_CALLS_TABLE)

_token: str | None = None
_last_dns_ip: str | None = None
_admin_token: str | None = None
_ce_cache: tuple[float, dict[str, Any]] | None = None


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


# ---------- Superadmin summary ----------


def _is_admin(event: dict[str, Any]) -> bool:
    global _admin_token
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False
    provided = auth[len("Bearer ") :]
    if not provided:
        return False
    if _admin_token is None:
        _admin_token = sm.get_secret_value(SecretId=ADMIN_TOKEN_SECRET)["SecretString"].strip()
    return hmac.compare_digest(provided.encode(), _admin_token.encode())


def _plain(value: Any) -> Any:
    """DynamoDB returns Decimal; JSON needs float."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _all_calls() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = calls_table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round(p * (len(ordered) - 1))]


def _fetch_aws_cost(today: date) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": "unavailable",
        "scope": "account",  # no cost-allocation tag filter, so this is the whole account
        "month_to_date_usd": None,
        "daily": [],
        "by_service": [],
        "error": None,
    }
    month_start = today.replace(day=1)
    # CE needs Start < End; on the 1st, End must be tomorrow.
    month_end = today if today > month_start else today + timedelta(days=1)
    try:
        daily_res = ce.get_cost_and_usage(
            TimePeriod={
                "Start": (today - timedelta(days=30)).isoformat(),
                "End": today.isoformat(),
            },
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )
        svc_res = ce.get_cost_and_usage(
            TimePeriod={"Start": month_start.isoformat(), "End": month_end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
    except Exception as exc:  # Cost Explorer not enabled, no permission, throttling...
        out["error"] = str(exc)
        return out

    daily = [
        {
            "date": r["TimePeriod"]["Start"],
            "usd": float(r["Total"]["UnblendedCost"]["Amount"]),
        }
        for r in daily_res["ResultsByTime"]
    ]
    services = [
        {
            "service": g["Keys"][0],
            "usd": float(g["Metrics"]["UnblendedCost"]["Amount"]),
        }
        for r in svc_res["ResultsByTime"]
        for g in r.get("Groups", [])
    ]
    services.sort(key=lambda s: s["usd"], reverse=True)
    out.update(
        source="cost-explorer",
        month_to_date_usd=round(sum(s["usd"] for s in services), 4),
        daily=daily,
        by_service=services[:8],
    )
    return out


def _aws_cost() -> dict[str, Any]:
    global _ce_cache
    now = time.time()
    if _ce_cache is not None and now - _ce_cache[0] < CE_CACHE_S:
        return _ce_cache[1]
    result = _fetch_aws_cost(datetime.now(UTC).date())
    _ce_cache = (now, result)
    return result


def admin_summary() -> dict[str, Any]:
    calls = sorted(
        (_plain(item) for item in _all_calls()),
        key=lambda c: str(c.get("started_at") or ""),  # ISO-8601 strings sort by time
        reverse=True,
    )
    turn_ms = [float(t) for c in calls for t in c.get("per_turn_ms") or []]
    costs = [c["est_cost_usd"] for c in calls if c.get("est_cost_usd") is not None]
    seconds = [float(c["duration_s"]) for c in calls if c.get("duration_s") is not None]
    return {
        "backend": status(),
        "totals": {
            "calls": len(calls),
            "minutes": round(sum(seconds) / 60, 3),
            "est_cost_usd": round(sum(costs), 4) if costs else None,
            "p50_ms": _percentile(turn_ms, 0.5),
            "p95_ms": _percentile(turn_ms, 0.95),
        },
        "calls": calls[:100],
        "aws_cost": _aws_cost(),
    }


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
        if method == "GET" and path.endswith("/admin/summary"):
            if not _is_admin(event):
                return _json(401, {"error": "unauthorized"})
            return _json(200, admin_summary())
        return _json(404, {"error": "not found"})
    except Exception as exc:  # keep CORS headers on failures too
        print(f"error: {exc!r}")
        return _json(500, {"error": str(exc)})
