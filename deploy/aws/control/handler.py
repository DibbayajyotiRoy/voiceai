"""Control plane for the demo Fargate task (Lambda + Function URL + 5-min sweep).

POST /start        -> ECS desiredCount 0 -> 1
GET  /status       -> stopped | starting | ready (+ url once https /health answers,
                       stage = stopped|provisioning|pulling|starting|securing|ready, since_s)
GET  /admin/summary -> superadmin view: backend state, call history, totals, AWS cost, traffic.
                       Requires `Authorization: Bearer <voiceai/admin-token>`.
GET  /report/{share_id} -> public view of one finished call (no auth, cached 1 h).
POST /track        -> page and call events from the site. Requires `X-Track-Secret`
                       (`voiceai/track-secret`), so only the Vercel frontend can write.
EventBridge  -> stop the task when idle (active == 0 and idle > 15 min) or after 60 min.

DNS: on each new task public IP, upsert the A record via the Vercel REST API.
"""

import base64
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

CLUSTER = os.environ.get("CLUSTER", "voiceai-demo")
SERVICE = os.environ.get("SERVICE", "voiceai-demo")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "demo-api.dibbayajyoti.com")
DNS_ZONE = os.environ.get("DNS_ZONE", "dibbayajyoti.com")
DNS_RECORD = os.environ.get("DNS_RECORD", "demo-api")
VERCEL_SECRET_ID = os.environ.get("VERCEL_SECRET_ID", "voiceai/vercel-token")
VERCEL_TEAM_ID = os.environ.get("VERCEL_TEAM_ID", "")
ADMIN_TOKEN_SECRET = os.environ.get("ADMIN_TOKEN_SECRET", "voiceai/admin-token")
TRACK_SECRET_NAME = os.environ.get("TRACK_SECRET_NAME", "voiceai/track-secret")
DEMO_CALLS_TABLE = os.environ.get("DEMO_CALLS_TABLE", "voiceai-demo-calls")
DEMO_EVENTS_TABLE = os.environ.get("DEMO_EVENTS_TABLE", "voiceai-demo-events")
SHARE_INDEX = "share_id-index"
APP_CONTAINER = "app"  # container name in deploy/aws/demo.yaml

IDLE_LIMIT_S = 900
MAX_RUNTIME_S = 3600
CE_CACHE_S = 6 * 3600  # Cost Explorer charges $0.01 per request
EVENT_TTL_S = 180 * 24 * 3600
TRACK_MAX_BYTES = 4096
TRAFFIC_POINTS = 500

EVENT_TYPES = {"page_view", "call_started", "call_completed", "report_shared", "report_opened"}
CHANNELS = {"x", "linkedin", "whatsapp", "copy", "native"}
UTM_KEYS = ("source", "medium", "campaign", "content")
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")
COUNTRY = re.compile(r"[A-Za-z]{2}")

ecs = boto3.client("ecs")
ec2 = boto3.client("ec2")
sm = boto3.client("secretsmanager")
ce = boto3.client("ce")
dynamodb = boto3.resource("dynamodb")
calls_table = dynamodb.Table(DEMO_CALLS_TABLE)
events_table = dynamodb.Table(DEMO_EVENTS_TABLE)

_token: str | None = None
_last_dns_ip: str | None = None
_admin_token: str | None = None
_track_secret: str | None = None
_ce_cache: tuple[float, dict[str, Any]] | None = None


def _json(code: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    # CORS headers come from the Function URL config; do not add them here.
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }


def _headers(event: dict[str, Any]) -> dict[str, str]:
    return {k.lower(): v for k, v in (event.get("headers") or {}).items()}


def _desired() -> int:
    svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
    return int(svc["desiredCount"])


def _set_desired(n: int) -> None:
    ecs.update_service(cluster=CLUSTER, service=SERVICE, desiredCount=n)


def _running_task() -> dict[str, Any] | None:
    """Newest non-stopped task (provisioning..running) with its public IP, or None."""
    arns = ecs.list_tasks(cluster=CLUSTER, serviceName=SERVICE, desiredStatus="RUNNING")["taskArns"]
    if not arns:
        return None
    described = ecs.describe_tasks(cluster=CLUSTER, tasks=arns)["tasks"]
    tasks = [t for t in described if t["lastStatus"] != "STOPPED"]
    if not tasks:
        return None
    task = max(tasks, key=lambda t: t.get("createdAt") or datetime.min.replace(tzinfo=UTC))
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
    app = next((c for c in task.get("containers", []) if c.get("name") == APP_CONTAINER), {})
    return {
        "lastStatus": task["lastStatus"],
        "createdAt": task.get("createdAt"),
        "startedAt": task.get("startedAt"),
        "pullStartedAt": task.get("pullStartedAt"),
        "pullStoppedAt": task.get("pullStoppedAt"),
        "app_health": app.get("healthStatus"),
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


def _stage(task: dict[str, Any] | None) -> str:
    """Startup stage of a non-stopped task. 'securing' means ready pending the https check."""
    if task is None:
        return "provisioning"
    last = task["lastStatus"]
    if last == "PROVISIONING" or (last in ("PENDING", "ACTIVATING") and not task["pullStartedAt"]):
        return "provisioning"
    if last in ("PENDING", "ACTIVATING") and not task["pullStoppedAt"]:
        return "pulling"
    # Without a container healthCheck (demo.yaml has none) ECS reports UNKNOWN, not absent.
    # Only an explicit UNHEALTHY holds the stage; the https /health check gates "ready".
    if last != "RUNNING" or task["ip"] is None or task["app_health"] == "UNHEALTHY":
        return "starting"
    return "securing"


def status() -> dict[str, Any]:
    if _desired() == 0:
        return {"state": "stopped", "url": None, "stage": "stopped", "since_s": None}
    task = _running_task()
    since_s = None if task is None else (datetime.now(UTC) - task["createdAt"]).total_seconds()
    if task is not None and task["ip"] is not None:
        _ensure_dns(task["ip"])
    stage = _stage(task)
    if stage == "securing" and _healthy():
        return {
            "state": "ready",
            "url": f"https://{PUBLIC_HOST}",
            "stage": "ready",
            "since_s": since_s,
        }
    return {"state": "starting", "url": None, "stage": stage, "since_s": since_s}


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
    auth = _headers(event).get("authorization", "")
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


def _scan_all(table: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round(p * (len(ordered) - 1))]


def _traffic(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Page, call and share counts from plain (float) event rows. Pure, no AWS calls."""
    by_type = Counter(e.get("type") for e in events)
    visitors = {e["visitor"] for e in events if e.get("visitor")}
    shares = Counter(
        e["channel"] for e in events if e.get("type") == "report_shared" and e.get("channel")
    )
    utm = Counter(
        e["utm"]["source"]
        for e in events
        if e.get("type") == "page_view" and (e.get("utm") or {}).get("source")
    )
    countries: dict[str, dict[str, Any]] = {}
    for e in events:
        geo = e.get("geo")
        if not geo:
            continue
        row = countries.setdefault(
            geo["country"], {"country": geo["country"], "views": 0, "calls": 0, "opens": 0}
        )
        kind = e.get("type")
        if kind == "page_view":
            row["views"] += 1
        elif kind == "call_started":
            row["calls"] += 1
        elif kind == "report_opened":
            row["opens"] += 1
    located = sorted(
        (e for e in events if e.get("geo")),
        key=lambda e: str(e.get("ts") or ""),
        reverse=True,
    )[:TRAFFIC_POINTS]
    return {
        "page_views": by_type["page_view"],
        "unique_visitors": len(visitors),
        "calls_started": by_type["call_started"],
        "calls_completed": by_type["call_completed"],
        "report_opens": by_type["report_opened"],
        "shares_by_channel": dict(shares),
        "utm_sources": [{"source": s, "views": n} for s, n in utm.most_common(10)],
        "by_country": sorted(countries.values(), key=lambda r: (-r["views"], r["country"])),
        "points": [
            {
                "lat": e["geo"]["lat"],
                "lon": e["geo"]["lon"],
                "type": e.get("type"),
                "city": e["geo"].get("city"),
                "country": e["geo"].get("country"),
            }
            for e in located
        ],
    }


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
        (_plain(item) for item in _scan_all(calls_table)),
        key=lambda c: str(c.get("started_at") or ""),  # ISO-8601 strings sort by time
        reverse=True,
    )
    turn_ms = [float(t) for c in calls for t in c.get("per_turn_ms") or []]
    costs = [c["est_cost_usd"] for c in calls if c.get("est_cost_usd") is not None]
    seconds = [float(c["duration_s"]) for c in calls if c.get("duration_s") is not None]
    events = [_plain(item) for item in _scan_all(events_table)]
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
        "traffic": _traffic(events),
        "aws_cost": _aws_cost(),
    }


# ---------- Public share report ----------


def public_report(share_id: str) -> dict[str, Any] | None:
    """Finished call by share id, without ttl or token counts. None when not found."""
    if not HEX32.fullmatch(share_id):
        return None
    resp = calls_table.query(
        IndexName=SHARE_INDEX,
        KeyConditionExpression=Key("share_id").eq(share_id),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    report = _plain(items[0])
    report.pop("ttl", None)
    report.pop("tokens", None)
    return report


# ---------- Traffic events from the site ----------


def _track_ok(event: dict[str, Any]) -> bool:
    global _track_secret
    provided = _headers(event).get("x-track-secret", "")
    if not provided:
        return False
    if _track_secret is None:
        _track_secret = sm.get_secret_value(SecretId=TRACK_SECRET_NAME)["SecretString"].strip()
    return hmac.compare_digest(provided.encode(), _track_secret.encode())


def _no_constants(name: str) -> Any:
    raise ValueError(f"invalid number {name}")  # NaN and Infinity are not valid event data


def _text(
    obj: dict[str, Any],
    key: str,
    max_len: int,
    *,
    required: bool = False,
    pattern: re.Pattern[str] | None = None,
) -> str | None:
    value = obj.get(key)
    if value is None:
        if required:
            raise ValueError(f"{key} is required")
        return None
    if not isinstance(value, str) or len(value) > max_len:
        raise ValueError(f"invalid {key}")
    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(f"invalid {key}")
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | Decimal) and not isinstance(value, bool)


def _geo(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid geo")
    geo: dict[str, Any] = raw
    country = _text(geo, "country", 2, required=True, pattern=COUNTRY)
    lat, lon = geo.get("lat"), geo.get("lon")
    if not _is_number(lat) or not -90 <= lat <= 90:
        raise ValueError("invalid lat")
    if not _is_number(lon) or not -180 <= lon <= 180:
        raise ValueError("invalid lon")
    out: dict[str, Any] = {"country": (country or "").upper(), "lat": lat, "lon": lon}
    for key, max_len in (("region", 60), ("city", 80)):
        value = _text(geo, key, max_len)
        if value is not None:
            out[key] = value
    return out


def _event_item(body: Any) -> dict[str, Any]:
    """Validated row for the events table. Unknown keys are dropped, so nothing else is stored."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    kind = body.get("type")
    if kind not in EVENT_TYPES:
        raise ValueError("invalid type")
    channel = _text(body, "channel", 16)
    if channel is not None and channel not in CHANNELS:
        raise ValueError("invalid channel")
    item: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttl": int(time.time()) + EVENT_TTL_S,
        "type": kind,
        "path": _text(body, "path", 200, required=True),
    }
    optional = {
        "share_id": _text(body, "share_id", 32, pattern=HEX32),
        "visitor": _text(body, "visitor", 64, pattern=HEX64),
        "channel": channel,
        "referrer_host": _text(body, "referrer_host", 100),
    }
    item.update({k: v for k, v in optional.items() if v is not None})
    if body.get("utm") is not None:
        utm_raw = body["utm"]
        if not isinstance(utm_raw, dict):
            raise ValueError("invalid utm")
        item["utm"] = {k: v for k in UTM_KEYS if (v := _text(utm_raw, k, 60)) is not None}
    if body.get("geo") is not None:
        item["geo"] = _geo(body["geo"])
    return item


def track(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    if len(raw) > TRACK_MAX_BYTES:
        return _json(400, {"error": "body too large"})
    try:
        item = _event_item(json.loads(raw, parse_float=Decimal, parse_constant=_no_constants))
    except ValueError as exc:  # JSONDecodeError, binascii.Error and UnicodeError are ValueErrors
        return _json(400, {"error": str(exc)})
    events_table.put_item(Item=item)
    return _json(200, {"ok": True})


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
        share = re.search(r"/report/([^/]+)$", path)
        if method == "GET" and share:
            report = public_report(share.group(1))
            if report is None:
                return _json(404, {"error": "not found"})
            return _json(200, report, {"cache-control": "public, max-age=3600"})
        if method == "POST" and path.endswith("/track"):
            if not _track_ok(event):
                return _json(401, {"error": "unauthorized"})
            return track(event)
        return _json(404, {"error": "not found"})
    except Exception as exc:  # keep CORS headers on failures too
        print(f"error: {exc!r}")
        return _json(500, {"error": str(exc)})
