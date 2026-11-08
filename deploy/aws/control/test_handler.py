"""Stubbed checks for control/handler.py: start, status, idle-stop rules, admin summary,
public share report, and POST /track."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import handler  # noqa: E402  (deploy/aws/control is on sys.path under pytest)


class FakeECS:
    def __init__(self, desired=0, tasks=()):
        self.desired = desired
        self.tasks = list(tasks)
        self.updates = []

    def describe_services(self, cluster, services):
        return {"services": [{"desiredCount": self.desired}]}

    def update_service(self, cluster, service, desiredCount):
        self.updates.append(desiredCount)
        self.desired = desiredCount

    def list_tasks(self, cluster, serviceName, desiredStatus):
        return {"taskArns": [t["taskArn"] for t in self.tasks]}

    def describe_tasks(self, cluster, tasks):
        return {"tasks": self.tasks}


def task(last="RUNNING", started=None, **extra):
    """Task created 60s ago, image pulled, app container HEALTHY; override via kwargs."""
    now = datetime.now(UTC)
    base = {
        "taskArn": "arn:task",
        "lastStatus": last,
        "createdAt": now - timedelta(seconds=60),
        "startedAt": started or now,
        "pullStartedAt": now - timedelta(seconds=50),
        "pullStoppedAt": now - timedelta(seconds=40),
        "containers": [{"name": "app", "healthStatus": "HEALTHY"}],
        "attachments": [
            {
                "type": "ElasticNetworkInterface",
                "details": [{"name": "networkInterfaceId", "value": "eni-1"}],
            }
        ],
    }
    return {**base, **extra}


def install(monkeypatch, ecs, ip="203.0.113.7", health=True, idle=None, dns=None):
    monkeypatch.setattr(handler, "ecs", ecs)
    monkeypatch.setattr(
        handler,
        "ec2",
        SimpleNamespace(
            describe_network_interfaces=lambda NetworkInterfaceIds: {
                "NetworkInterfaces": [{"Association": {"PublicIp": ip}}]
            }
        ),
    )
    monkeypatch.setattr(handler, "_healthy", lambda: health)
    monkeypatch.setattr(handler, "_idle", lambda: idle)
    calls = [] if dns is None else dns
    monkeypatch.setattr(handler, "_ensure_dns", lambda ip: calls.append(ip))
    monkeypatch.setattr(handler, "_last_dns_ip", None)
    return calls


def test_start_sets_desired_one(monkeypatch):
    ecs = FakeECS(desired=0)
    install(monkeypatch, ecs)
    out = handler.start()
    assert ecs.updates == [1]
    assert out["state"] == "starting"  # no task yet


def test_start_idempotent_when_already_one(monkeypatch):
    ecs = FakeECS(desired=1)
    install(monkeypatch, ecs)
    handler.start()
    assert ecs.updates == []


def test_status_stopped_when_desired_zero(monkeypatch):
    install(monkeypatch, FakeECS(desired=0))
    assert handler.status() == {
        "state": "stopped",
        "url": None,
        "stage": "stopped",
        "since_s": None,
    }


def test_status_provisioning_when_desired_one_without_task(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[]))
    assert handler.status() == {
        "state": "starting",
        "url": None,
        "stage": "provisioning",
        "since_s": None,
    }


def test_status_provisioning_while_task_provisioning(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task(last="PROVISIONING")]))
    out = handler.status()
    assert (out["state"], out["stage"]) == ("starting", "provisioning")
    assert out["since_s"] == pytest.approx(60, abs=5)


def test_status_pulling_between_pull_start_and_stop(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task(last="PENDING", pullStoppedAt=None)]))
    assert handler.status()["stage"] == "pulling"


def test_status_starting_after_pull_while_pending(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task(last="PENDING")]))
    out = handler.status()
    assert (out["state"], out["stage"]) == ("starting", "starting")


def test_status_starting_when_app_container_unhealthy(monkeypatch):
    unhealthy = [{"name": "app", "healthStatus": "UNHEALTHY"}]
    dns = []
    install(monkeypatch, FakeECS(desired=1, tasks=[task(containers=unhealthy)]), dns=dns)
    out = handler.status()
    assert (out["state"], out["stage"]) == ("starting", "starting")
    assert dns == ["203.0.113.7"]  # IP is known, so DNS still gets pointed


def test_status_securing_when_healthy_but_https_down(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task()]), health=False)
    out = handler.status()
    assert (out["state"], out["stage"], out["url"]) == ("starting", "securing", None)


def test_status_ready_points_dns_and_returns_url(monkeypatch):
    dns = []
    install(monkeypatch, FakeECS(desired=1, tasks=[task()]), dns=dns)
    out = handler.status()
    assert (out["state"], out["stage"]) == ("ready", "ready")
    assert out["url"] == "https://demo-api.dibbayajyoti.com"
    assert out["since_s"] == pytest.approx(60, abs=5)
    assert dns == ["203.0.113.7"]


def test_status_ignores_stopped_tasks(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task(last="STOPPED")]))
    assert handler.status()["stage"] == "provisioning"


def test_status_starting_while_pending(monkeypatch):
    install(monkeypatch, FakeECS(desired=1, tasks=[task(last="PENDING")]))
    assert handler.status()["state"] == "starting"


def test_sweep_stops_when_idle_and_no_active_calls(monkeypatch):
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle={"idle_seconds": 1000, "active": 0})
    assert handler.sweep()["reason"] == "idle"
    assert ecs.updates == [0]


def test_sweep_does_not_stop_active_call_even_if_idle_large(monkeypatch):
    # Orchestrator rule: backend last_activity only updates on connect/disconnect.
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle={"idle_seconds": 1000, "active": 1})
    assert handler.sweep()["action"] == "none"
    assert ecs.updates == []


def test_sweep_does_not_stop_under_idle_threshold(monkeypatch):
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle={"idle_seconds": 600, "active": 0})
    handler.sweep()
    assert ecs.updates == []


def test_sweep_does_not_stop_when_idle_endpoint_unreachable(monkeypatch):
    ecs = FakeECS(desired=1, tasks=[task()])
    install(monkeypatch, ecs, idle=None)
    handler.sweep()
    assert ecs.updates == []


def test_sweep_stops_after_max_runtime_even_if_active(monkeypatch):
    old = datetime.now(UTC) - timedelta(minutes=61)
    ecs = FakeECS(desired=1, tasks=[task(started=old)])
    install(monkeypatch, ecs, idle={"idle_seconds": 0, "active": 1})
    assert handler.sweep()["reason"] == "max-runtime"
    assert ecs.updates == [0]


def test_sweep_noop_when_already_stopped(monkeypatch):
    ecs = FakeECS(desired=0)
    install(monkeypatch, ecs)
    assert handler.sweep()["reason"] == "stopped"
    assert ecs.updates == []


# ---------- /admin/summary ----------

TOKEN = "a" * 32


class FakeSM:
    def __init__(self, secret=TOKEN):
        self.secret = secret

    def get_secret_value(self, SecretId):
        return {"SecretString": self.secret}


class FakeTable:
    """Two scan pages: the first returns LastEvaluatedKey, so pagination is exercised."""

    def __init__(self):
        def item(call_id, started, duration_s, cost, per_turn):
            return {
                "call_id": call_id,
                "started_at": started,
                "duration_s": None if duration_s is None else Decimal(duration_s),
                "turns": Decimal(len(per_turn)),
                "interruptions": Decimal(0),
                "greeting_latency_ms": Decimal(120),
                "latency_ms": {
                    "p50": Decimal(200),
                    "p95": Decimal(300),
                    "min": Decimal(100),
                    "max": Decimal(300),
                },
                "per_turn_ms": [Decimal(x) for x in per_turn],
                "user_talk_s": Decimal("10"),
                "agent_talk_s": Decimal("12"),
                "tokens": {"input": Decimal(500), "output": Decimal(200)},
                "est_cost_usd": None if cost is None else Decimal(cost),
                "model": "amazon.nova-2-sonic-v1:0",
                "region": "us-east-1",
                "measured_at": started,
                "ttl": Decimal(1900000000),
            }

        self.pages = [
            {
                "Items": [item("a", "2026-11-07T10:00:00Z", "150", "0.10", [100, 300])],
                "LastEvaluatedKey": {"call_id": "a"},
            },
            {
                "Items": [
                    item("b", "2026-11-08T09:00:00Z", "90", "0.05", [200]),
                    # Missing duration and cost: skipped in minutes, treated as 0 in cost.
                    item("c", "2026-11-06T08:00:00Z", None, None, []),
                ]
            },
        ]
        self.scans = 0

    def scan(self, **kwargs):
        page = self.pages[self.scans]
        self.scans += 1
        return page


class FakeCE:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def get_cost_and_usage(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Cost Explorer is not enabled for this account")
        if kwargs.get("GroupBy"):

            def group(service, amount):
                return {"Keys": [service], "Metrics": {"UnblendedCost": {"Amount": amount}}}

            return {
                "ResultsByTime": [
                    {"Groups": [group("Amazon EC2", "1.25"), group("Amazon S3", "0.5")]}
                ]
            }
        return {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-11-07", "End": "2026-11-08"},
                    "Total": {"UnblendedCost": {"Amount": "1.75"}},
                }
            ]
        }


@pytest.fixture
def admin(monkeypatch):
    install(monkeypatch, FakeECS(desired=0))  # backend reports "stopped", no DNS touched
    monkeypatch.setattr(handler, "_admin_token", None)
    monkeypatch.setattr(handler, "_ce_cache", None)
    monkeypatch.setattr(handler, "sm", FakeSM())
    monkeypatch.setattr(handler, "calls_table", FakeTable())
    monkeypatch.setattr(handler, "events_table", FakeEvents())
    ce = FakeCE()
    monkeypatch.setattr(handler, "ce", ce)
    return SimpleNamespace(ce=ce)


def admin_event(auth=None):
    headers = {} if auth is None else {"authorization": auth}
    return {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": "/demo/admin/summary",
        "headers": headers,
    }


def test_admin_401_when_token_missing(admin):
    out = handler.handler(admin_event(), None)
    assert out["statusCode"] == 401
    assert json.loads(out["body"]) == {"error": "unauthorized"}
    assert admin.ce.calls == 0


def test_admin_401_when_token_wrong(admin):
    out = handler.handler(admin_event("Bearer " + "b" * 32), None)
    assert out["statusCode"] == 401


def test_admin_401_when_bearer_empty(admin):
    assert handler.handler(admin_event("Bearer "), None)["statusCode"] == 401


def test_admin_200_shape_with_stubbed_dynamo_and_ce(admin):
    out = handler.handler(admin_event(f"Bearer {TOKEN}"), None)
    assert out["statusCode"] == 200
    body = json.loads(out["body"])  # also proves Decimals were converted

    assert body["backend"] == {"state": "stopped", "url": None, "stage": "stopped", "since_s": None}
    assert body["totals"] == {
        "calls": 3,
        "minutes": 4.0,
        "est_cost_usd": 0.15,
        "p50_ms": 200.0,
        "p95_ms": 300.0,
    }
    assert [c["call_id"] for c in body["calls"]] == ["b", "a", "c"]  # newest first
    assert body["calls"][0]["per_turn_ms"] == [200.0]

    cost = body["aws_cost"]
    assert cost["source"] == "cost-explorer"
    assert cost["scope"] == "account"
    assert cost["error"] is None
    assert cost["month_to_date_usd"] == 1.75
    assert cost["by_service"][0] == {"service": "Amazon EC2", "usd": 1.25}
    assert cost["daily"] == [{"date": "2026-11-07", "usd": 1.75}]


def test_admin_cost_failure_is_unavailable_not_fatal(monkeypatch, admin):
    monkeypatch.setattr(handler, "ce", FakeCE(fail=True))
    out = handler.handler(admin_event(f"Bearer {TOKEN}"), None)
    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["aws_cost"]["source"] == "unavailable"
    assert "not enabled" in body["aws_cost"]["error"]
    assert body["aws_cost"]["month_to_date_usd"] is None
    assert body["totals"]["calls"] == 3


def test_admin_cost_cached_for_six_hours(admin):
    handler.handler(admin_event(f"Bearer {TOKEN}"), None)
    first = admin.ce.calls  # one DAILY + one MONTHLY call
    handler.handler(admin_event(f"Bearer {TOKEN}"), None)
    assert first == 2
    assert admin.ce.calls == 2  # second request served from cache


def test_unknown_container_health_still_reaches_securing() -> None:
    # Regression: ECS reports UNKNOWN when no container healthCheck exists; treating it as
    # "not healthy" kept every task at "starting" forever and nobody could call.
    task = {"lastStatus": "RUNNING", "ip": "1.2.3.4", "app_health": "UNKNOWN"}
    assert handler._stage(task) == "securing"


# ---------- /report/{share_id} (public) ----------

SHARE = "86fdbaf79dd94261b5ef4faf1ef5a854"


class FakeShareTable:
    """Answers the share_id-index query by matching the key value in the condition."""

    def __init__(self, items):
        self.items = items
        self.index = None

    def query(self, IndexName, KeyConditionExpression, Limit):
        self.index = IndexName
        _, value = KeyConditionExpression.get_expression()["values"]
        return {"Items": [i for i in self.items if i.get("share_id") == value][:Limit]}


def shared_item():
    return {
        "call_id": f"SmallWebRTCConnection#0-{SHARE}",
        "share_id": SHARE,
        "started_at": "2026-11-08T10:00:00Z",
        "duration_s": Decimal("12.5"),
        "turns": Decimal(2),
        "latency_ms": {"p50": Decimal("600"), "p95": Decimal("900")},
        "per_turn_ms": [Decimal("600.5")],
        "tokens": {"speech_in": Decimal(10)},
        "est_cost_usd": Decimal("0.0123"),
        "latency_basis": "model_end_of_turn",
        "ttl": Decimal(1900000000),
    }


def report_event(share_id):
    return {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": f"/demo/report/{share_id}",
        "headers": {},
    }


@pytest.fixture
def share(monkeypatch):
    table = FakeShareTable([shared_item()])
    monkeypatch.setattr(handler, "calls_table", table)
    return table


@pytest.mark.parametrize("bad", ["nope", SHARE.upper(), SHARE[:31], SHARE + "0", "g" * 32])
def test_report_404_for_malformed_share_id(share, bad):
    out = handler.handler(report_event(bad), None)
    assert out["statusCode"] == 404
    assert json.loads(out["body"]) == {"error": "not found"}
    assert share.index is None  # never queried


def test_report_404_for_unknown_share_id(share):
    out = handler.handler(report_event("0" * 32), None)
    assert out["statusCode"] == 404
    assert json.loads(out["body"]) == {"error": "not found"}


def test_report_200_public_strips_ttl_and_tokens(share):
    out = handler.handler(report_event(SHARE), None)  # no auth header on purpose
    assert out["statusCode"] == 200
    assert out["headers"]["cache-control"] == "public, max-age=3600"
    body = json.loads(out["body"])
    assert share.index == "share_id-index"
    assert "ttl" not in body
    assert "tokens" not in body
    assert body["est_cost_usd"] == pytest.approx(0.0123)  # kept, and a float
    assert body["duration_s"] == 12.5
    assert body["latency_ms"] == {"p50": 600.0, "p95": 900.0}
    assert body["latency_basis"] == "model_end_of_turn"
    assert body["share_id"] == SHARE


# ---------- POST /track ----------

TRACK = "t" * 40


class FakeEvents:
    def __init__(self, items=()):
        self.items = list(items)
        self.put: list[dict[str, Any]] = []

    def scan(self, **kwargs):
        return {"Items": self.items}

    def put_item(self, *, Item):
        self.put.append(Item)


@pytest.fixture
def track_env(monkeypatch):
    monkeypatch.setattr(handler, "sm", FakeSM(secret=TRACK))
    monkeypatch.setattr(handler, "_track_secret", None)
    events = FakeEvents()
    monkeypatch.setattr(handler, "events_table", events)
    return events


def track_event(raw, secret=TRACK):
    headers = {} if secret is None else {"X-Track-Secret": secret}  # header names are case-free
    return {
        "requestContext": {"http": {"method": "POST"}},
        "rawPath": "/demo/track",
        "headers": headers,
        "body": raw,
    }


def test_track_401_without_secret(track_env):
    out = handler.handler(track_event(json.dumps({"type": "page_view", "path": "/"}), None), None)
    assert out["statusCode"] == 401
    assert track_env.put == []


def test_track_401_with_wrong_secret(track_env):
    out = handler.handler(
        track_event(json.dumps({"type": "page_view", "path": "/"}), "x" * 40), None
    )
    assert out["statusCode"] == 401
    assert track_env.put == []


def test_track_stores_only_known_fields(track_env):
    body = {
        "type": "report_shared",
        "path": "/demo",
        "share_id": SHARE,
        "channel": "x",
        "utm": {"source": "x", "campaign": "launch", "term": "dropped"},
        "referrer_host": "t.co",
        "geo": {"country": "de", "region": "BE", "city": "Berlin", "lat": 52.52, "lon": 13.4},
        "visitor": "a" * 64,
        "ip": "203.0.113.9",
        "extra": 1,
    }
    out = handler.handler(track_event(json.dumps(body)), None)
    assert out["statusCode"] == 200
    assert json.loads(out["body"]) == {"ok": True}

    (item,) = track_env.put
    assert "ip" not in item and "extra" not in item
    assert "203.0.113.9" not in str(item)
    assert item["type"] == "report_shared"
    assert item["share_id"] == SHARE
    assert item["utm"] == {"source": "x", "campaign": "launch"}
    assert item["geo"] == {
        "country": "DE",
        "region": "BE",
        "city": "Berlin",
        "lat": Decimal("52.52"),
        "lon": Decimal("13.4"),
    }
    assert item["ts"].endswith("Z")
    assert uuid.UUID(item["event_id"]).version == 4
    now = int(datetime.now(UTC).timestamp())
    assert now + 179 * 86400 < item["ttl"] <= now + 180 * 86400 + 5


BAD_BODIES = [
    json.dumps({"type": "nope", "path": "/"}),
    json.dumps({"type": "page_view"}),  # path required
    json.dumps({"type": "page_view", "path": "/" * 201}),
    json.dumps({"type": "page_view", "path": "/", "share_id": "ABC"}),
    json.dumps({"type": "page_view", "path": "/", "visitor": "a" * 63}),
    json.dumps({"type": "report_shared", "path": "/", "channel": "myspace"}),
    json.dumps({"type": "page_view", "path": "/", "utm": {"source": "s" * 61}}),
    json.dumps({"type": "page_view", "path": "/", "utm": "source=x"}),
    json.dumps({"type": "page_view", "path": "/", "referrer_host": "r" * 101}),
    json.dumps({"type": "page_view", "path": "/", "geo": {"country": "USA", "lat": 1, "lon": 1}}),
    json.dumps({"type": "page_view", "path": "/", "geo": {"country": "US", "lat": 91, "lon": 1}}),
    json.dumps({"type": "page_view", "path": "/", "geo": {"country": "US", "lat": True, "lon": 1}}),
    json.dumps({"type": "page_view", "path": "/", "geo": {"country": "US", "lat": 1, "lon": 181}}),
    json.dumps({"type": "page_view", "path": "/", "geo": {"country": "US", "lat": 1}}),
    '{"type":"page_view","path":"/","geo":{"country":"US","lat":NaN,"lon":1}}',
    "[1, 2]",
    "{not json",
    json.dumps({"type": "page_view", "path": "/", "pad": "a" * 4096}),  # over 4 KB
]


@pytest.mark.parametrize("raw", BAD_BODIES)
def test_track_400_on_invalid_body(track_env, raw):
    out = handler.handler(track_event(raw), None)
    assert out["statusCode"] == 400
    assert "error" in json.loads(out["body"])
    assert track_env.put == []


# ---------- admin summary: traffic ----------


def test_admin_traffic_shape(admin, monkeypatch):
    def geo(country, lat, lon, city=None):
        g = {"country": country, "lat": Decimal(str(lat)), "lon": Decimal(str(lon))}
        if city:
            g["city"] = city
        return g

    rows = [
        {
            "type": "page_view",
            "ts": "2026-11-08T01:00:00Z",
            "visitor": "1" * 64,
            "utm": {"source": "x"},
            "geo": geo("US", 40.7, -74.0, "New York"),
        },
        {
            "type": "page_view",
            "ts": "2026-11-08T02:00:00Z",
            "visitor": "1" * 64,
            "utm": {"source": "x"},
            "geo": geo("US", 40.7, -74.0),
        },
        {
            "type": "page_view",
            "ts": "2026-11-08T03:00:00Z",
            "visitor": "2" * 64,
            "utm": {"source": "linkedin"},
            "geo": geo("DE", 52.5, 13.4),
        },
        {"type": "page_view", "ts": "2026-11-08T04:00:00Z", "visitor": "2" * 64},  # no geo
        {"type": "call_started", "ts": "2026-11-08T05:00:00Z", "geo": geo("DE", 52.5, 13.4)},
        {"type": "call_completed", "ts": "2026-11-08T06:00:00Z"},
        {"type": "report_shared", "ts": "2026-11-08T06:30:00Z", "channel": "x"},
        {"type": "report_shared", "ts": "2026-11-08T06:31:00Z", "channel": "copy"},
        {"type": "report_shared", "ts": "2026-11-08T06:32:00Z", "channel": "x"},
        {"type": "report_opened", "ts": "2026-11-08T07:00:00Z", "geo": geo("US", 40.7, -74.0)},
    ]
    monkeypatch.setattr(handler, "events_table", FakeEvents(rows))
    out = handler.handler(admin_event(f"Bearer {TOKEN}"), None)
    assert out["statusCode"] == 200
    traffic = json.loads(out["body"])["traffic"]

    assert traffic["page_views"] == 4
    assert traffic["unique_visitors"] == 2
    assert traffic["calls_started"] == 1
    assert traffic["calls_completed"] == 1
    assert traffic["report_opens"] == 1
    assert traffic["shares_by_channel"] == {"x": 2, "copy": 1}
    assert traffic["utm_sources"] == [
        {"source": "x", "views": 2},
        {"source": "linkedin", "views": 1},
    ]
    assert traffic["by_country"] == [
        {"country": "US", "views": 2, "calls": 0, "opens": 1},
        {"country": "DE", "views": 1, "calls": 1, "opens": 0},
    ]
    assert len(traffic["points"]) == 5  # the geo-less page view is not a point
    assert traffic["points"][0] == {
        "lat": 40.7,
        "lon": -74.0,
        "type": "report_opened",
        "city": None,
        "country": "US",
    }
    assert all(isinstance(p["lat"], float) for p in traffic["points"])


def test_traffic_points_capped_and_newest_first():
    rows = [
        {
            "type": "page_view",
            "ts": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
            "geo": {"country": "US", "lat": 1.0, "lon": 2.0},
        }
        for i in range(600)
    ]
    traffic = handler._traffic(rows)
    assert len(traffic["points"]) == handler.TRAFFIC_POINTS
    assert traffic["points"][0]["type"] == "page_view"
    assert traffic["page_views"] == 600
    assert traffic["by_country"] == [{"country": "US", "views": 600, "calls": 0, "opens": 0}]
